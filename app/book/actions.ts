import { redirect } from 'next/navigation';
import { z } from 'zod';
import { getSupabaseAdmin } from '@/lib/supabase/server';

const bookingSchema = z.object({
  full_name: z.string().min(2, 'Enter your name'),
  phone: z.string().min(10, 'Enter a valid phone number'),
  email: z.string().email('Enter a valid email'),
  target_move_date: z.string().min(1, 'Select a move date'),
  move_size: z.enum(["studio", "one_bedroom", "two_bedroom", "three_bedroom", "four_bedroom_plus", "commercial", "unknown"]),
  move_distance: z.enum(["local", "long_distance"]),
  origin_address: z.string().min(5, 'Enter your origin address'),
  destination_address: z.string().optional(),
  selected_slot: z.string().min(1, 'Pick a time slot'),
});

export async function createBookingAction(formData: FormData) {
  'use server';

  const raw = {
    full_name: formData.get('full_name')?.toString() ?? '',
    phone: formData.get('phone')?.toString() ?? '',
    email: formData.get('email')?.toString() ?? '',
    target_move_date: formData.get('target_move_date')?.toString() ?? '',
    move_size: formData.get('move_size')?.toString() ?? 'unknown',
    move_distance: formData.get('move_distance')?.toString() ?? 'local',
    origin_address: formData.get('origin_address')?.toString() ?? '',
    destination_address: formData.get('destination_address')?.toString() ?? '',
    selected_slot: formData.get('selected_slot')?.toString() ?? '',
  };

  const booking = bookingSchema.parse(raw);

  const start = new Date(booking.selected_slot);
  if (Number.isNaN(start.getTime())) {
    throw new Error('Selected slot is invalid');
  }

  const end = new Date(start.getTime() + 45 * 60 * 1000);
  const clientId = 1;
  const admin = getSupabaseAdmin() as any;

  const { data: leadData, error: leadError } = await admin
    .from('leads')
    .insert({
      client_id: clientId,
      status: 'pending_review',
      source: 'landing_page_form',
      full_name: booking.full_name,
      phone: booking.phone,
      email: booking.email,
      origin_address: booking.origin_address,
      destination_address: booking.move_distance === 'long_distance' ? booking.destination_address : null,
      target_move_date: booking.target_move_date,
      move_size: booking.move_size,
      move_distance: booking.move_distance,
    })
    .select('id')
    .single();

  if (leadError || !leadData?.id) {
    throw new Error(leadError?.message ?? 'Unable to create lead');
  }

  const { error: appointmentError } = await admin
    .from('appointments')
    .insert({
      client_id: clientId,
      lead_id: leadData.id,
      type: 'in_person',
      status: 'pending_review',
      scheduled_start: start.toISOString(),
      scheduled_end: end.toISOString(),
    });

  if (appointmentError) {
    throw new Error(appointmentError.message);
  }

  redirect('/book?submitted=true');
}
