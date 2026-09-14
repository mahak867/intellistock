import * as LucideIcons from "lucide-react";
import type { LucideProps } from "lucide-react";

interface IconPlaceholderProps extends LucideProps {
  lucide: keyof typeof LucideIcons;
  // Other icon-library props accepted for source compatibility with
  // upstream ReUI components, but unused — this app only ships lucide-react.
  tabler?: string;
  hugeicons?: string;
  phosphor?: string;
  remixicon?: string;
}

export function IconPlaceholder({
  lucide,
  tabler: _tabler,
  hugeicons: _hugeicons,
  phosphor: _phosphor,
  remixicon: _remixicon,
  ...props
}: IconPlaceholderProps) {
  const Icon = LucideIcons[lucide] as React.ComponentType<LucideProps>;
  if (!Icon) return null;
  return <Icon {...props} />;
}
