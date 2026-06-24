export default function PublicLandingPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-8 px-6 py-16 text-slate-950">
      <div className="space-y-4">
        <p className="text-sm uppercase tracking-[0.3em] text-slate-500">Customer landing page</p>
        <h1 className="text-4xl font-semibold sm:text-5xl">Springfield Moving Co.</h1>
        <p className="max-w-3xl text-lg leading-8 text-slate-700">
          Book your in-person moving estimate, see available slots, and submit your move details.
          This is the customer-facing landing page placeholder for the public site.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <a
          className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:border-slate-300"
          href="/admin/dashboard"
        >
          <h2 className="text-xl font-semibold">Admin dashboard →</h2>
          <p className="mt-2 text-sm text-slate-600">Approve bookings, review leads, and manage cross-client reports.</p>
        </a>

        <a
          className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:border-slate-300"
          href="/owner/dashboard"
        >
          <h2 className="text-xl font-semibold">Owner dashboard →</h2>
          <p className="mt-2 text-sm text-slate-600">View your leads, appointments, and performance metrics.</p>
        </a>
      </div>
    </main>
  );
}
