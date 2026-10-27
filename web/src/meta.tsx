import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Meta } from "./api";

const MetaContext = createContext<Meta | null>(null);

export function MetaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);
  return <MetaContext.Provider value={meta}>{children}</MetaContext.Provider>;
}

export function useMeta() {
  return useContext(MetaContext);
}

export function useLanguageLabel() {
  const meta = useMeta();
  return (code: string) => meta?.languages.find((l) => l.code === code)?.label ?? code;
}
