import { useEffect, useState } from 'react';
import { getDesktopConnection, type DesktopConnection } from './desktop';

export function useDesktopConnection() {
  const [connection, setConnection] = useState<DesktopConnection | undefined>(() =>
    typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window ? undefined : { isolated: false, baseUrl: '' });
  useEffect(() => {
    let active = true;
    void getDesktopConnection().then((value) => { if (active) setConnection(value); }).catch((error) => {
      // Never expose production controls when native isolation status is unknown.
      if (active) setConnection({ isolated: true, baseUrl: '', error: String(error) });
    });
    return () => { active = false; };
  }, []);
  return connection;
}
