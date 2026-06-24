import BookingWizard from '@/components/booking-wizard';
import { createBookingAction } from './actions';
import Link from 'next/link';

interface BookPageProps {
  searchParams?: { submitted?: string };
}

export default function BookPage({ searchParams }: BookPageProps) {
  const submitted = searchParams?.submitted === 'true';

  return (
    <main className="bg-slate-50 min-h-screen px-6 py-16 text-slate-950 sm:px-10">
      <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-start">
        <section className="space-y-6">
          <div className="inline-flex items-center gap-3 rounded-full bg-amber-100 px-4 py-2 text-sm font-semibold text-amber-900">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            Booking widget
          </div>
          <div className="space-y-4">
            <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
              Request your free moving estimate
            </h1>
            <p className="max-w-xl text-lg leading-8 text-slate-700">
              Answer a few quick questions and choose a placeholder slot. We’ll review it and confirm your appointment shortly.
            </p>
          </div>

          <div className="rounded-4xl border border-amber-200 bg-white p-8 shadow-sm">
            <p className="text-sm font-semibold text-slate-900">Need help?</p>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              Call our booking line and we’ll walk you through the estimate process.
            </p>
            <p className="mt-4 text-2xl font-semibold text-amber-700">(417) 555-0198</p>
          </div>

          <div className="rounded-4xl border border-slate-200 bg-white p-8 shadow-sm">
            <h2 className="text-xl font-semibold">What to expect</h2>
            <ul className="mt-4 space-y-3 text-sm leading-7 text-slate-600">
              <li>• A review-first booking flow for the first 3 months.</li>
              <li>• Appointment requests are queued with status pending review.</li>
              <li>• We confirm via email and SMS once the slot is approved.</li>
            </ul>
          </div>
        </section>

        <section>
          {submitted ? (
            <div className="rounded-[2rem] border border-slate-200 bg-white p-10 shadow-xl">
              <div className="mb-6 rounded-3xl bg-amber-100 px-5 py-4 text-amber-900">
                <p className="font-semibold">Request received</p>
              </div>
              <h2 className="text-3xl font-semibold text-slate-950">Thank you — your estimate request is pending review.</h2>
              <p className="mt-4 text-sm leading-7 text-slate-600">
                We have recorded your details and appointment time. A member of our team will confirm your booking soon via email or phone.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link href="/" className="rounded-full bg-slate-950 px-6 py-3 text-sm font-semibold text-white transition hover:bg-slate-800">
                  Back to homepage
                </Link>
                <Link href="/book" className="rounded-full border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-950 transition hover:bg-slate-50">
                  Submit another request
                </Link>
              </div>
            </div>
          ) : (
            <BookingWizard action={createBookingAction} />
          )}
        </section>
      </div>
    </main>
  );
}
