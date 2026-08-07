import { useState } from "react";

import type { ApiClient } from "../api/client";
import type { InstrumentSearchResult } from "../api/market-contracts";
import { useMarketSearchQuery } from "../api/queries";

export interface InstrumentSelection {
  instrument_id: string;
  name: string;
  kind: string;
}

export function InstrumentSearchPicker({
  client,
  value,
  onChange,
  className,
  ariaLabel = "搜索证券",
  placeholder = "输入代码或名称",
}: {
  client: ApiClient;
  value: InstrumentSelection | null;
  onChange: (selection: InstrumentSelection | null) => void;
  className?: string;
  ariaLabel?: string;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const searchQuery = useMarketSearchQuery(client, query);
  const trimmed = query.trim();

  if (value !== null) {
    return (
      <div className={`instrument-picker instrument-picker--selected${className ? ` ${className}` : ""}`}>
        <strong>{value.name}</strong>
        <span>{value.instrument_id}</span>
        <button type="button" onClick={() => onChange(null)}>更换</button>
      </div>
    );
  }

  return (
    <div className={`instrument-picker${className ? ` ${className}` : ""}`}>
      <input
        aria-label={ariaLabel}
        type="search"
        value={query}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(event) => setQuery(event.target.value)}
      />
      {trimmed.length >= 2 ? (
        <div className="instrument-picker__results">
          {searchQuery.isLoading ? <p>正在搜索东财证券目录…</p> : null}
          {searchQuery.isError ? <p role="alert">证券目录搜索失败，请稍后重试</p> : null}
          {searchQuery.data?.map((item) => (
            <button
              key={item.instrument_id}
              type="button"
              onClick={() => {
                onChange(toSelection(item));
                setQuery("");
              }}
            >
              <strong>{item.name}</strong>
              <span>{item.instrument_id}</span>
              <em>选择</em>
            </button>
          ))}
          {!searchQuery.isLoading && !searchQuery.isError && searchQuery.data?.length === 0 ? (
            <p>没有找到可订阅证券</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function toSelection(item: InstrumentSearchResult): InstrumentSelection {
  return { instrument_id: item.instrument_id, name: item.name, kind: item.kind };
}
