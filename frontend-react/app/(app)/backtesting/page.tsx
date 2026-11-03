"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

// The old page needed a trained BiLSTM per ticker and Yahoo access. The backtester on the Tools page does
// walk-forward testing with Indian costs on whatever data source is configured, so this route now goes there.
export default function BacktestingRedirect() {
  const router = useRouter();
  React.useEffect(() => { router.replace("/tools?tool=bt"); }, [router]);
  return <p className="text-sm text-muted-foreground">Opening the backtester…</p>;
}
