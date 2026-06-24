'use client';

import { format, addDays, set } from 'date-fns';
import { useMemo, useState } from 'react';
import { ArrowRight, CalendarDays, CheckCircle2, MapPin, Phone } from 'lucide-react';

interface BookingWizardProps {
  action: (formData: FormData) => Promise<void>;
}

const slotBaseTimes = ['09:00', '10:15', '11:30', '13:00', '14:15', '15:30', '16:45'];

const humanizeSize = {
  studio: 'Studio',
  one_bedroom: '1 Bedroom',
  two_bedroom: '2 Bedroom',
  three_bedroom: '3 Bedroom',
  four_bedroom_plus: '4+ Bedroom',
  commercial: 'Commercial',
  unknown: 'Unknown',
};

export default function BookingWizard({ action }: BookingWizardProps) {
  const [step, setStep] = useState(1);
  const [moveDistance, setMoveDistance] = useState<'local' | 'long_distance'>('local');
  const [selectedSlot, setSelectedSlot] = useState('');
  const [form, setForm] = useState({
    target_move_date: '',
    move_size: 'one_bedroom',
    move_distance: 'local',
    origin_address: '',
    destination_address: '',
    full_name: '',
    phone: '',
    email: '',
  });

  const slots = useMemo(() => {
    const baseDate = addDays(new Date(), 1);
    return slotBaseTimes.map((time) => {
      const [hours, minutes] = time.split(':').map(Number);
      const slotDate = set(baseDate, { hours, minutes, seconds: 0, milliseconds: 0 });
      return {
        value: slotDate.toISOString(),
        label: format(slotDate, 'EEE MMM d, h:mm a'),
      };
    });
  }, []);

  const handleNext = () => {
    if (step === 2 && moveDistance === 'long_distance' && !form.destination_address.trim()) {
      return;
    }
    setStep((current) => Math.min(current + 1, 4));
  };

  const handlePrevious = () => {
    setStep((current) => Math.max(current - 1, 1));
  };

  return (
    <div className="rounded-4xl border border-slate-200 bg-white p-8 shadow-xl sm:p-10">
      <div className="mb-8 flex flex-col gap-2">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-700">Free estimate</p>
        <h2 className="text-3xl font-semibold tracking-tight text-slate-950">Book your moving estimate</h2>
        <p className="max-w-2xl text-sm leading-6 text-slate-600 sm:text-base">
          Complete the short booking flow and we’ll review your request before confirming your appointment.
        </p>
      </div>

      <div className="mb-8 grid gap-3 sm:grid-cols-5">
        {[1, 2, 3, 4].map((index) => (
          <div
            key={index}
            className={`rounded-2xl border p-3 text-center text-sm ${step === index ? 'border-amber-400 bg-amber-50 text-amber-900' : 'border-slate-200 bg-slate-50 text-slate-500'}`}
          >
            Step {index}
          </div>
        ))}
      </div>

      <form action={action} className="space-y-8">
        {step === 1 && (
          <section className="space-y-6">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="target_move_date">
                Target move date
              </label>
              <input
                id="target_move_date"
                name="target_move_date"
                type="date"
                value={form.target_move_date}
                onChange={(event) => setForm({ ...form, target_move_date: event.target.value })}
                className="w-full rounded-3xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-950 outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                required
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-3 text-sm font-medium text-slate-700">Move size</p>
                <div className="grid gap-3">
                  {Object.entries(humanizeSize).map(([value, label]) => (
                    <label key={value} className="flex items-center gap-3 rounded-3xl border border-slate-200 px-4 py-3 text-sm text-slate-700 transition hover:border-amber-300">
                      <input
                        type="radio"
                        name="move_size"
                        value={value}
                        checked={form.move_size === value}
                        onChange={(event) => setForm({ ...form, move_size: event.target.value })}
                        className="h-4 w-4 accent-amber-600"
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-3 text-sm font-medium text-slate-700">Distance</p>
                <div className="grid gap-3">
                  <label className="flex items-center gap-3 rounded-3xl border border-slate-200 px-4 py-3 text-sm text-slate-700 transition hover:border-amber-300">
                    <input
                      type="radio"
                      name="move_distance"
                      value="local"
                      checked={form.move_distance === 'local'}
                      onChange={(event) => {
                        setForm({ ...form, move_distance: event.target.value });
                        setMoveDistance('local');
                      }}
                      className="h-4 w-4 accent-amber-600"
                    />
                    Local move
                  </label>
                  <label className="flex items-center gap-3 rounded-3xl border border-slate-200 px-4 py-3 text-sm text-slate-700 transition hover:border-amber-300">
                    <input
                      type="radio"
                      name="move_distance"
                      value="long_distance"
                      checked={form.move_distance === 'long_distance'}
                      onChange={(event) => {
                        setForm({ ...form, move_distance: event.target.value });
                        setMoveDistance('long_distance');
                      }}
                      className="h-4 w-4 accent-amber-600"
                    />
                    Long-distance
                  </label>
                </div>
              </div>
            </div>
          </section>
        )}

        {step === 2 && (
          <section className="space-y-6">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="origin_address">
                Origin address
              </label>
              <input
                id="origin_address"
                name="origin_address"
                type="text"
                value={form.origin_address}
                onChange={(event) => setForm({ ...form, origin_address: event.target.value })}
                placeholder="123 Main St, Springfield, MO"
                className="w-full rounded-3xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-950 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                required
              />
            </div>

            {moveDistance === 'long_distance' && (
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="destination_address">
                  Destination address
                </label>
                <input
                  id="destination_address"
                  name="destination_address"
                  type="text"
                  value={form.destination_address}
                  onChange={(event) => setForm({ ...form, destination_address: event.target.value })}
                  placeholder="City, State or full address"
                  className="w-full rounded-3xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-950 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                  required={moveDistance === 'long_distance'}
                />
              </div>
            )}
          </section>
        )}

        {step === 3 && (
          <section className="space-y-6">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="full_name">
                Full name
              </label>
              <input
                id="full_name"
                name="full_name"
                type="text"
                value={form.full_name}
                onChange={(event) => setForm({ ...form, full_name: event.target.value })}
                placeholder="Jordan Hayes"
                className="w-full rounded-3xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-950 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                required
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="phone">
                  Phone number
                </label>
                <input
                  id="phone"
                  name="phone"
                  type="tel"
                  value={form.phone}
                  onChange={(event) => setForm({ ...form, phone: event.target.value })}
                  placeholder="(417) 555-0123"
                  className="w-full rounded-3xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-950 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                  required
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="email">
                  Email address
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  value={form.email}
                  onChange={(event) => setForm({ ...form, email: event.target.value })}
                  placeholder="you@example.com"
                  className="w-full rounded-3xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-950 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                  required
                />
              </div>
            </div>
          </section>
        )}

        {step === 4 && (
          <section className="space-y-6">
            <div className="space-y-3">
              <p className="text-sm font-medium text-slate-700">Pick a time slot</p>
              <p className="max-w-2xl text-sm leading-6 text-slate-600">
                These slots are a placeholder for the real availability engine we’ll connect later.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {slots.map((slot) => (
                <button
                  key={slot.value}
                  type="button"
                  onClick={() => setSelectedSlot(slot.value)}
                  className={`rounded-3xl border p-4 text-left transition ${selectedSlot === slot.value ? 'border-amber-400 bg-amber-50 text-amber-900' : 'border-slate-200 bg-slate-50 text-slate-700 hover:border-amber-300'}`}
                >
                  <p className="font-semibold">{slot.label}</p>
                  <p className="mt-1 text-sm text-slate-500">45-minute estimate window</p>
                </button>
              ))}
            </div>

            <input type="hidden" name="selected_slot" value={selectedSlot} />
          </section>
        )}

        <input type="hidden" name="move_distance" value={form.move_distance} />
        <input type="hidden" name="move_size" value={form.move_size} />
        <input type="hidden" name="origin_address" value={form.origin_address} />
        <input type="hidden" name="destination_address" value={form.destination_address} />
        <input type="hidden" name="full_name" value={form.full_name} />
        <input type="hidden" name="phone" value={form.phone} />
        <input type="hidden" name="email" value={form.email} />
        <input type="hidden" name="target_move_date" value={form.target_move_date} />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button
            type="button"
            onClick={handlePrevious}
            disabled={step === 1}
            className="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white px-5 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Back
          </button>

          {step < 4 ? (
            <button
              type="button"
              onClick={handleNext}
              className="inline-flex items-center justify-center rounded-full bg-amber-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-700"
            >
              Continue
              <ArrowRight className="ml-2 h-4 w-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!selectedSlot}
              className="inline-flex items-center justify-center rounded-full bg-amber-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Confirm booking
            </button>
          )}
        </div>

        <div className="rounded-3xl bg-slate-50 p-5 text-sm leading-6 text-slate-600">
          <div className="flex items-center gap-2 font-semibold text-slate-900">
            <CheckCircle2 className="h-4 w-4 text-amber-600" />
            What happens next
          </div>
          <p className="mt-2">
            Your request will be reviewed by our team. We’ll confirm availability and lock the appointment via SMS or email.
          </p>
        </div>
      </form>
    </div>
  );
}
