import { useEffect, useState } from "react";

function sanitizePath(pathname) {
  return pathname === "/settings" ? "/settings" : "/";
}

export function useAppRoute() {
  const [route, setRoute] = useState(() => sanitizePath(window.location.pathname));

  useEffect(() => {
    function handlePopstate() {
      setRoute(sanitizePath(window.location.pathname));
    }
    window.addEventListener("popstate", handlePopstate);
    return () => window.removeEventListener("popstate", handlePopstate);
  }, []);

  function navigate(nextPath) {
    const sanitized = sanitizePath(nextPath);
    if (sanitized === route) {
      return;
    }
    window.history.pushState({}, "", sanitized);
    setRoute(sanitized);
  }

  return { route, navigate };
}
