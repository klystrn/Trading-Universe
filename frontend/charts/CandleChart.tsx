"use client";

/** Candlestick chart on TradingView Lightweight Charts (spec 38), with the
 *  technical overlays and the signal's entry / stop / target as price lines. */

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { CandleResponse } from "@/lib/types";

export function CandleChart({ data, height = 380 }: { data: CandleResponse; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9aa5bb",
        fontFamily: "SF Mono, ui-monospace, Menlo, monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.10)" },
      timeScale: { borderColor: "rgba(255,255,255,0.10)", timeVisible: false },
      crosshair: { mode: 0 },
      // Pinned: the axis formatter calls Date.toLocaleString, and a browser
      // whose default locale is not a valid BCP-47 tag would throw inside it
      // and leave the chart blank.
      localization: { locale: "en-US" },
      autoSize: true,
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      // Not plain red/green: teal up, amber-coral down (spec 49).
      upColor: "#4fd1a5",
      downColor: "#e8886b",
      borderVisible: false,
      wickUpColor: "#4fd1a5",
      wickDownColor: "#e8886b",
    });
    candles.setData(
      data.candles.map((c) => ({
        time: c.time as UTCTimestamp,
        open: c.open, high: c.high, low: c.low, close: c.close,
      })),
    );

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "rgba(154,165,187,0.25)",
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      data.candles.map((c) => ({
        time: c.time as UTCTimestamp,
        value: c.volume,
        color: c.close >= c.open ? "rgba(79,209,165,0.28)" : "rgba(232,136,107,0.28)",
      })),
    );

    // Moving-average overlays, computed client-side from the same candles.
    const closes = data.candles.map((c) => c.close);
    const addMa = (window: number, color: string, ema = false) => {
      const points: { time: UTCTimestamp; value: number }[] = [];
      let prev: number | null = null;
      const k = 2 / (window + 1);
      for (let i = 0; i < closes.length; i += 1) {
        if (i < window - 1) continue;
        let value: number;
        if (ema) {
          value = prev == null
            ? closes.slice(0, window).reduce((a, b) => a + b, 0) / window
            : closes[i] * k + prev * (1 - k);
          prev = value;
        } else {
          value = closes.slice(i - window + 1, i + 1).reduce((a, b) => a + b, 0) / window;
        }
        points.push({ time: data.candles[i].time as UTCTimestamp, value });
      }
      chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        .setData(points);
    };
    addMa(20, "rgba(90,209,230,0.75)", true);
    addMa(50, "rgba(232,194,107,0.65)");
    addMa(200, "rgba(183,155,214,0.6)");

    // Entry / stop / target from the most recent signal.
    const marker = data.markers[data.markers.length - 1];
    if (marker) {
      const line = (price: number, color: string, title: string) =>
        candles.createPriceLine({
          price, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title,
        });
      line(marker.entry, "#5ad1e6", "entry");
      line(marker.stop, "#e8886b", "stop");
      line(marker.target, "#4fd1a5", "target");
    }

    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [data, height]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}
