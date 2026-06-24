import { ReactNode } from 'react';

interface SiteShellProps {
  title: string;
  description: string;
  children: ReactNode;
}

export function SiteShell({ title, description, children }: SiteShellProps) {
  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-16 text-slate-950">
      <div className="space-y-6">
        <div className="space-y-3">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-500">{title}</p>
          <h1 className="text-4xl font-semibold sm:text-5xl">{description}</h1>
        </div>
        <div className="rounded-3xl border border-slate-200 bg-white/90 p-6 shadow-sm">{children}</div>
      </div>
    </main>
  );
}
