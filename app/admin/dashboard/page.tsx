export default function AdminDashboardPage() {
  return (
    <main className="mx-auto min-h-screen max-w-5xl px-6 py-16 text-slate-950">
      <div className="space-y-4">
        <p className="text-sm uppercase tracking-[0.3em] text-slate-500">Admin dashboard</p>
        <h1 className="text-4xl font-semibold sm:text-5xl">Approval queue & leads</h1>
        <p className="max-w-3xl text-lg leading-8 text-slate-700">
          This is the admin surface for Lando to approve pending bookings, review all clients, and manage payouts.
        </p>
      </div>
    </main>
  );
}
