import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { OpportunityDrawer } from "./OpportunityDrawer";

/** Opens the opportunity drawer on top of whatever page you're on (`?opp=<id>`). */
export function useOpenOpportunity() {
  const [params, setParams] = useSearchParams();
  return useCallback(
    (id: string | null) => {
      const next = new URLSearchParams(params);
      if (id) next.set("opp", id);
      else next.delete("opp");
      setParams(next);
    },
    [params, setParams],
  );
}

/** Mounted once in App, so the Pipeline, Leads, Opportunities and Activities pages share one drawer. */
export function OpportunityDrawerHost() {
  const [params] = useSearchParams();
  const openOpportunity = useOpenOpportunity();
  const id = params.get("opp");
  if (!id) return null;
  return <OpportunityDrawer opportunityId={id} onClose={() => openOpportunity(null)} />;
}
