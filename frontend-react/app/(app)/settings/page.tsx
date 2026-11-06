"use client";

import * as React from "react";
import { useAuth } from "@/lib/auth-context";
import { updateProfile } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

export default function SettingsPage() {
  const { token, user } = useAuth();
  const [fullName, setFullName] = React.useState(user?.full_name || "");
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (user?.full_name) Promise.resolve().then(() => setFullName(user.full_name));
  }, [user]);

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      await updateProfile(token, fullName);
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h1 className="font-display text-2xl font-semibold mb-6">Settings</h1>

      <div className="grid gap-4 max-w-lg">
        <Card>
          <CardHeader>
            <CardTitle className="text-foreground text-base">Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSave} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" value={user?.email || ""} disabled />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="fullName">Full name</Label>
                <Input
                  id="fullName"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </Button>
                {saved && <span className="text-xs text-success">Saved.</span>}
                {saveError && <span role="alert" className="text-xs text-destructive">Not saved: {saveError}</span>}
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-foreground text-base">API access</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Personal API key management is coming in a future release.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
