import type { Options } from "klinecharts";

export const marketChartTheme: Options["styles"] = {
  grid: {
    show: true,
    horizontal: { color: "rgba(44, 81, 84, 0.12)", size: 1, style: "dashed", dashedValue: [3, 4] },
    vertical: { color: "rgba(44, 81, 84, 0.09)", size: 1, style: "dashed", dashedValue: [3, 4] },
  },
  candle: {
    bar: {
      upColor: "#e44f56",
      downColor: "#18a46f",
      noChangeColor: "#718486",
      upBorderColor: "#e44f56",
      downBorderColor: "#18a46f",
      noChangeBorderColor: "#718486",
      upWickColor: "#e44f56",
      downWickColor: "#18a46f",
      noChangeWickColor: "#718486",
    },
    area: {
      lineColor: "#078d97",
      lineSize: 2,
      smooth: false,
      backgroundColor: [
        { offset: 0, color: "rgba(7, 141, 151, 0.22)" },
        { offset: 1, color: "rgba(7, 141, 151, 0.015)" },
      ],
      point: {
        show: true,
        color: "#078d97",
        radius: 2.5,
        rippleColor: "rgba(7, 141, 151, 0.25)",
        rippleRadius: 7,
        animation: false,
        animationDuration: 0,
      },
    },
    tooltip: {
      showRule: "follow_cross",
      showType: "standard",
    },
  },
  xAxis: {
    axisLine: { color: "rgba(44, 81, 84, 0.22)", size: 1 },
    tickLine: { color: "rgba(44, 81, 84, 0.2)", size: 1, length: 3 },
    tickText: {
      color: "#687d80",
      family: "IBM Plex Mono, Cascadia Mono, monospace",
      size: 11,
      weight: "400",
    },
  },
  yAxis: {
    axisLine: { color: "rgba(44, 81, 84, 0.22)", size: 1 },
    tickLine: { color: "rgba(44, 81, 84, 0.2)", size: 1, length: 3 },
    tickText: {
      color: "#687d80",
      family: "IBM Plex Mono, Cascadia Mono, monospace",
      size: 11,
      weight: "400",
    },
  },
  separator: {
    color: "rgba(44, 81, 84, 0.18)",
    size: 1,
    fill: true,
    activeBackgroundColor: "rgba(7, 141, 151, 0.08)",
  },
  crosshair: {
    show: true,
    horizontal: {
      line: { color: "#486f73", size: 1, style: "dashed", dashedValue: [4, 3] },
      text: {
        show: false,
        color: "#f4f8f7",
        backgroundColor: "#355d61",
        borderColor: "#355d61",
        borderSize: 0,
        borderRadius: 2,
        paddingLeft: 5,
        paddingRight: 5,
        paddingTop: 3,
        paddingBottom: 3,
        size: 11,
        family: "IBM Plex Mono, Cascadia Mono, monospace",
        weight: "500",
      },
    },
    vertical: {
      line: { color: "#486f73", size: 1, style: "dashed", dashedValue: [4, 3] },
      text: {
        show: true,
        color: "#f4f8f7",
        backgroundColor: "#355d61",
        borderColor: "#355d61",
        borderSize: 0,
        borderRadius: 2,
        paddingLeft: 5,
        paddingRight: 5,
        paddingTop: 3,
        paddingBottom: 3,
        size: 11,
        family: "IBM Plex Mono, Cascadia Mono, monospace",
        weight: "500",
      },
    },
  },
};
