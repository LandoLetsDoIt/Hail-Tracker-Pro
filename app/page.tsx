import Link from 'next/link';

export default function Home() {
  return (
    <main className="bg-amber-50 text-slate-950">
      <section className="mx-auto flex min-h-screen max-w-6xl flex-col justify-center px-6 py-16 sm:px-10 lg:flex-row lg:items-center lg:gap-16">
        <div className="max-w-2xl space-y-8">
          <div className="inline-flex items-center gap-3 rounded-full bg-white/90 px-4 py-2 text-sm font-semibold text-amber-900 shadow-sm shadow-amber-200">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            Trusted moving specialists in Springfield, MO
          </div>

          <div className="space-y-5">
            <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
              Local moving estimates with fast approval and friendly service.
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-slate-700 sm:text-xl">
              Book a free on-site moving estimate in minutes. We handle the details, keep your schedule smooth, and confirm your appointment after review.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href="/book"
              className="inline-flex items-center justify-center rounded-full bg-amber-700 px-8 py-4 text-base font-semibold text-white shadow-lg shadow-amber-200 transition hover:bg-amber-800"
            >
              Book Free Estimate
            </Link>
            <div className="rounded-full border border-amber-200 bg-white px-6 py-4 text-sm text-slate-700">
              <p className="text-xs uppercase tracking-[0.3em] text-amber-800">Call us</p>
              <p className="mt-2 text-2xl font-semibold">(417) 555-0198</p>
              <p className="mt-1 text-sm text-slate-500">Placeholder business phone</p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            {['Same-day callback', 'Transparent pricing', 'Friendly local crew'].map((item) => (
              <div key={item} className="rounded-3xl bg-white p-5 shadow-sm">
                <p className="text-base font-semibold text-slate-900">{item}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-12 lg:mt-0">
          <div className="rounded-[2rem] bg-slate-950 p-8 text-white shadow-2xl shadow-slate-900/20 sm:p-10">
            <div className="mb-6 flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-amber-500/20" />
              <div>
                <p className="text-sm uppercase tracking-[0.3em] text-amber-300">Estimate preview</p>
                <p className="text-sm text-slate-300">Simple booking, no hidden fees.</p>
              </div>
            </div>
            <div className="space-y-4">
              <div className="rounded-3xl bg-slate-800 p-5">
                <p className="text-sm uppercase tracking-[0.3em] text-slate-400">Move type</p>
                <p className="mt-2 text-xl font-semibold">2 bedroom local move</p>
              </div>
              <div className="rounded-3xl bg-slate-800 p-5">
                <p className="text-sm uppercase tracking-[0.3em] text-slate-400">Estimate time</p>
                <p className="mt-2 text-xl font-semibold">45 minutes</p>
              </div>
              <div className="rounded-3xl bg-slate-800 p-5">
                <p className="text-sm uppercase tracking-[0.3em] text-slate-400">Service radius</p>
                <p className="mt-2 text-xl font-semibold">45 minutes from Springfield</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 pb-16 sm:px-10">
        <div className="grid gap-6 sm:grid-cols-3">
          {[
            { label: 'Rated 5 stars', content: '“Friendly, punctual, and careful with our belongings.”' },
            { label: 'Trusted locally', content: 'Serving Springfield and surrounding neighborhoods.' },
            { label: 'Easy booking', content: 'Free estimate requests are reviewed before confirmation.' },
          ].map((item) => (
            <div key={item.label} className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <p className="text-sm font-semibold text-amber-700">{item.label}</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">{item.content}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
