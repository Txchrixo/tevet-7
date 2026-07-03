"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartSpec } from "@/lib/types";

// Map series color keys (from the mock data) to the Tevet-7 palette.
const COLOR_MAP: Record<string, string> = {
  accent: "#A8C090",
  primary: "#5A6B4A",
  foreground: "#E8E0C9",
  muted: "#A4A096",
  border: "#605E58",
};

function colorFor(name: string | undefined, fallback: string): string {
  return (name && COLOR_MAP[name]) || fallback;
}

const AXIS_TICK = {
  fontFamily: "Caudex, serif",
  fontSize: 11,
  fill: "#A4A096",
} as const;

interface ChartDisplayProps {
  spec: ChartSpec;
}

export function ChartDisplay({ spec }: ChartDisplayProps) {
  const isBar = spec.type === "bar";
  return (
    <div className="rounded-md border border-border bg-background p-3">
      {spec.title && (
        <div className="mb-2 flex items-center justify-between">
          <span className="font-heading text-xs text-foreground">
            {spec.title}
          </span>
        </div>
      )}
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {isBar ? (
            <BarChart
              data={spec.data}
              margin={{ top: 8, right: 8, left: -16, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#605E58"
                vertical={false}
                opacity={0.4}
              />
              <XAxis
                dataKey={spec.xKey}
                tick={AXIS_TICK}
                axisLine={false}
                tickLine={false}
                interval={0}
                angle={-12}
                textAnchor="end"
                height={48}
              />
              <YAxis
                tick={AXIS_TICK}
                axisLine={false}
                tickLine={false}
                width={40}
              />
              <Tooltip
                cursor={{ fill: "#3A4A3C", opacity: 0.5 }}
                contentStyle={{
                  borderRadius: 6,
                  border: "1px solid #605E58",
                  background: "#2D3A2F",
                  color: "#E8E0C9",
                  fontFamily: "Manrope, sans-serif",
                  fontSize: 12,
                }}
                labelStyle={{ color: "#A4A096" }}
                formatter={(value: number) =>
                  spec.unit ? `${value} ${spec.unit}` : `${value}`
                }
              />
              {spec.series.map((s) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  fill={colorFor(s.color, "#A8C090")}
                  radius={[3, 3, 0, 0]}
                  maxBarSize={48}
                />
              ))}
            </BarChart>
          ) : (
            <LineChart
              data={spec.data}
              margin={{ top: 8, right: 8, left: -16, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#605E58"
                vertical={false}
                opacity={0.4}
              />
              <XAxis
                dataKey={spec.xKey}
                tick={AXIS_TICK}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={AXIS_TICK}
                axisLine={false}
                tickLine={false}
                width={40}
              />
              <Tooltip
                cursor={{ stroke: "#605E58", strokeWidth: 1 }}
                contentStyle={{
                  borderRadius: 6,
                  border: "1px solid #605E58",
                  background: "#2D3A2F",
                  color: "#E8E0C9",
                  fontFamily: "Manrope, sans-serif",
                  fontSize: 12,
                }}
                labelStyle={{ color: "#A4A096" }}
                formatter={(value: number) =>
                  spec.unit ? `${value} ${spec.unit}` : `${value}`
                }
              />
              {spec.series.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label}
                  stroke={colorFor(s.color, "#5A6B4A")}
                  strokeWidth={2}
                  dot={{ r: 3, fill: colorFor(s.color, "#5A6B4A") }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
      {/* Legend */}
      <div className="mt-2 flex flex-wrap gap-3">
        {spec.series.map((s) => (
          <div key={s.key} className="flex items-center gap-1.5">
            <span
              className="size-2.5 rounded-sm"
              style={{ background: colorFor(s.color, "#A8C090") }}
            />
            <span className="text-[11px] text-muted-foreground">{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
