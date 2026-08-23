import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://lcpyyilepfnlmbrwdzcv.supabase.co';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey && supabaseAnonKey.trim().length > 10);

export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey)
  : {
      auth: {
        getSession: async () => ({ data: { session: null }, error: null }),
        onAuthStateChange: (callback) => {
          return { data: { subscription: { unsubscribe: () => {} } } };
        },
        signInWithPassword: async ({ email, password }) => {
          // Local fallback demo mode when anon key is not yet pasted in .env
          return {
            data: {
              session: {
                access_token: 'demo_merchant_token_' + Date.now(),
                user: {
                  id: 'merchant_demo_' + Math.random().toString(36).substring(2, 8),
                  email: email || 'merchant@example.com',
                  user_metadata: {
                    business_name: email ? email.split('@')[0].toUpperCase() + ' CORP' : 'DEMO MERCHANT'
                  }
                }
              }
            },
            error: null
          };
        },
        signUp: async ({ email, password, options }) => {
          return {
            data: {
              session: {
                access_token: 'demo_merchant_token_' + Date.now(),
                user: {
                  id: 'merchant_demo_' + Math.random().toString(36).substring(2, 8),
                  email: email,
                  user_metadata: options?.data || { business_name: 'DEMO MERCHANT' }
                }
              }
            },
            error: null
          };
        },
        signOut: async () => ({ error: null })
      }
    };
