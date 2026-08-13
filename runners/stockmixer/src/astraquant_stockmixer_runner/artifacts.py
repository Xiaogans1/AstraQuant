"""Deterministic, pickle-free StockMixer model and prediction artifacts."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from torch import Tensor

from .contracts import StockMixerRequest, canonical_digest
from .training import TrainedFold, TrainingConfig

STOCKMIXER_RESPONSE_SCHEMA = "astraquant.stockmixer-training-response/v1"
_MODEL_MAGIC = b"AQSMOD01"


@dataclass(frozen=True, slots=True)
class TrainingArtifact:
    content_digest: str
    response_path: Path
    model_path: Path
    predictions_path: Path


def write_training_artifact(
    result: TrainedFold,
    *,
    request: StockMixerRequest,
    config: TrainingConfig,
    output_root: Path,
) -> TrainingArtifact:
    if output_root.exists():
        raise ValueError("training artifact output_root must not already exist")
    if result.test_predictions.shape != (
        len(result.test_sample_ids),
        len(request.instrument_ids),
    ):
        raise ValueError("test prediction coverage does not match request instruments")
    output_root.mkdir(parents=True)
    model_path = output_root / "model-state.bin"
    predictions_path = output_root / "predictions.parquet"
    response_path = output_root / "response.json"
    model_path.write_bytes(_encode_model_state(result.model.state_dict()))
    _write_predictions(result, request, predictions_path)

    config_value = asdict(config)
    config_value["scales"] = list(config.scales)
    body: dict[str, Any] = {
        "schema_version": STOCKMIXER_RESPONSE_SCHEMA,
        "request_content_digest": request.content_digest,
        "fold_id": result.fold_id,
        "training_config": config_value,
        "training_config_digest": canonical_digest(config_value),
        "code_digest": _code_digest(),
        "model_state_digest": result.model_state_digest,
        "best_epoch": result.best_epoch,
        "epoch_history": [asdict(item) for item in result.history],
        "split": asdict(result.split),
        "normalizer": {
            "mean": [float(value) for value in result.normalizer.mean],
            "scale": [float(value) for value in result.normalizer.scale],
            "count": result.normalizer.count,
        },
        "instruments": list(request.instrument_ids),
        "prediction_rows": int(result.test_predictions.numel()),
        "files": {
            "model": {"path": model_path.name, "digest": _file_digest(model_path)},
            "predictions": {
                "path": predictions_path.name,
                "digest": _file_digest(predictions_path),
            },
        },
    }
    content_digest = canonical_digest(body)
    response = {"content_digest": content_digest, **body}
    response_path.write_text(
        json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return TrainingArtifact(content_digest, response_path, model_path, predictions_path)


def load_model_state(path: Path) -> dict[str, Tensor]:
    """Load only primitive tensor bytes; never execute pickle or imported code."""

    payload = path.read_bytes()
    if len(payload) < 16 or payload[:8] != _MODEL_MAGIC:
        raise ValueError("StockMixer model artifact magic mismatch")
    header_size = struct.unpack("<Q", payload[8:16])[0]
    header_end = 16 + header_size
    if header_end > len(payload):
        raise ValueError("StockMixer model header is truncated")
    header = json.loads(payload[16:header_end].decode("utf-8"))
    if not isinstance(header, list):
        raise ValueError("StockMixer model header must be an array")
    raw = payload[header_end:]
    result: dict[str, Tensor] = {}
    expected_offset = 0
    for item in header:
        if not isinstance(item, dict) or set(item) != {
            "dtype",
            "length",
            "name",
            "offset",
            "shape",
        }:
            raise ValueError("StockMixer model tensor header mismatch")
        name = item["name"]
        shape = item["shape"]
        offset = item["offset"]
        length = item["length"]
        if (
            not isinstance(name, str)
            or not name
            or name in result
            or not isinstance(shape, list)
            or not all(isinstance(value, int) and value >= 0 for value in shape)
            or not isinstance(offset, int)
            or not isinstance(length, int)
            or offset != expected_offset
            or length < 0
            or offset + length > len(raw)
        ):
            raise ValueError("StockMixer model tensor bounds mismatch")
        dtype = np.dtype(item["dtype"])
        array = np.frombuffer(raw[offset : offset + length], dtype=dtype)
        expected_elements = int(np.prod(shape, dtype=np.int64))
        if array.size != expected_elements:
            raise ValueError("StockMixer model tensor shape mismatch")
        result[name] = torch.from_numpy(array.copy().reshape(shape))
        expected_offset += length
    if expected_offset != len(raw):
        raise ValueError("StockMixer model artifact contains trailing bytes")
    return result


def _encode_model_state(state: dict[str, Tensor]) -> bytes:
    header: list[dict[str, object]] = []
    chunks: list[bytes] = []
    offset = 0
    for name in sorted(state):
        tensor = state[name].detach().cpu().contiguous()
        array = tensor.numpy()
        chunk = array.tobytes(order="C")
        header.append(
            {
                "name": name,
                "dtype": array.dtype.str,
                "shape": list(array.shape),
                "offset": offset,
                "length": len(chunk),
            }
        )
        chunks.append(chunk)
        offset += len(chunk)
    encoded_header = json.dumps(
        header, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return _MODEL_MAGIC + struct.pack("<Q", len(encoded_header)) + encoded_header + b"".join(chunks)


def _write_predictions(
    result: TrainedFold, request: StockMixerRequest, path: Path
) -> None:
    rows = []
    scores = result.test_predictions.detach().cpu()
    for row_index, (sample_id, decision_time_us) in enumerate(
        zip(result.test_sample_ids, result.test_decision_times_us, strict=True)
    ):
        for stock_index, instrument_id in enumerate(request.instrument_ids):
            rows.append(
                {
                    "fold_id": result.fold_id,
                    "sample_id": sample_id,
                    "decision_time_us": decision_time_us,
                    "instrument_id": instrument_id,
                    "score": float(scores[row_index, stock_index]),
                }
            )
    schema = pa.schema(
        [
            pa.field("fold_id", pa.string(), nullable=False),
            pa.field("sample_id", pa.int64(), nullable=False),
            pa.field("decision_time_us", pa.int64(), nullable=False),
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("score", pa.float32(), nullable=False),
        ],
        metadata={b"schema_version": STOCKMIXER_RESPONSE_SCHEMA.encode("ascii")},
    )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=False,
    )


def _code_digest() -> str:
    package = Path(__file__).resolve().parent
    names = ("artifacts.py", "contracts.py", "dataset.py", "loss.py", "model.py", "training.py")
    evidence = [
        {"path": name, "sha256": hashlib.sha256((package / name).read_bytes()).hexdigest()}
        for name in names
    ]
    return canonical_digest(evidence)


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
