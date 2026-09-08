import { z } from 'zod'

/*
 * These mirror the DRF serializers in apps/accounts/serializers.py so client
 * and server validation stay aligned (PRD §8.3). The client copy is a UX
 * convenience -- the server revalidates everything regardless.
 */

const email = z
  .string()
  .min(1, 'Email is required.')
  .email('Enter a valid email address.')

/*
 * Matches what Django actually enforces (AUTH_PASSWORD_VALIDATORS): at least
 * 8 characters and not entirely numeric. The server also rejects common
 * passwords from its own list, which the client cannot check -- so that one
 * comes back as a server error.
 */
const password = z
  .string()
  .min(8, 'Password must be at least 8 characters.')
  .refine((value) => !/^\d+$/.test(value), {
    message: 'Password cannot be only numbers.',
  })

// Bangladesh mobile numbers: 01XXXXXXXXX, optionally +880-prefixed.
const phone = z
  .string()
  .regex(/^(?:\+?880|0)1[3-9]\d{8}$/, 'Enter a valid Bangladeshi mobile number.')

export const loginSchema = z.object({
  email,
  password: z.string().min(1, 'Password is required.'),
})

export const registerSchema = z
  .object({
    full_name: z.string().min(1, 'Please tell us your name.').max(150),
    email,
    phone: phone.or(z.literal('')).optional(),
    password,
    confirm_password: z.string().min(1, 'Please confirm your password.'),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: 'Passwords do not match.',
    path: ['confirm_password'],
  })

export const passwordResetRequestSchema = z.object({ email })

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password.'),
    new_password: password,
    confirm_password: z.string().min(1, 'Please confirm your new password.'),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: 'Passwords do not match.',
    path: ['confirm_password'],
  })

export const passwordResetConfirmSchema = z
  .object({
    new_password: password,
    confirm_password: z.string().min(1, 'Please confirm your password.'),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: 'Passwords do not match.',
    path: ['confirm_password'],
  })

export const addressSchema = z.object({
  recipient_name: z.string().min(1, 'Recipient name is required.').max(150),
  phone,
  division: z.string().min(1, 'Division is required.'),
  district: z.string().min(1, 'District is required.'),
  upazila: z.string().max(64).optional().or(z.literal('')),
  area: z.string().max(128).optional().or(z.literal('')),
  street: z.string().min(1, 'Street address is required.').max(255),
  postcode: z.string().max(12).optional().or(z.literal('')),
  is_default: z.boolean().optional(),
})
