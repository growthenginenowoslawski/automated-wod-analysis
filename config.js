// Public settings. The Supabase key here is the publishable key: it can only do what the
// database's security rules allow (for the test: add a result, never read anyone's).
export const CONFIG = {
  assets: 'self',          // 'self' = tracking library and model served by this site; 'cdn' = public CDNs
  supabaseUrl: '',
  supabaseKey: '',
};
