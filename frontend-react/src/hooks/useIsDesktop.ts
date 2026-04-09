import { useState, useEffect } from 'react';

const MD_BREAKPOINT = 768;

export function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(() => window.innerWidth >= MD_BREAKPOINT);

  useEffect(() => {
    const handler = () => setIsDesktop(window.innerWidth >= MD_BREAKPOINT);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return isDesktop;
}
