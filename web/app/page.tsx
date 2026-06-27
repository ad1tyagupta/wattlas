import { OpportunityRadar } from "@/components/opportunity-radar";
import { loadSnapshot } from "@/lib/snapshot/load";

export const dynamic = "force-static";

export default async function Home() {
  const snapshot = await loadSnapshot();
  return <OpportunityRadar snapshot={snapshot} />;
}
