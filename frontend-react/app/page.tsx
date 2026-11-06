"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function RootPage() {
  const router = useRouter();
  const { token, loading } = useAuth();

  React.useEffect(() => {
    if (!loading) router.replace(token ? "/dashboard" : "/login");
  }, [loading, token, router]);

  return (
    <div className="flex h-dvh items-center justify-center bg-background text-muted-foreground text-sm">
      Loading…
    </div>
  );
}
