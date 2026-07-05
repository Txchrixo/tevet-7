import { BrandMark } from "@/components/producer-copilot/brand-mark";

export const metadata = { title: "About - Tevet-7" };

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-2xl mx-auto px-4 py-20">
        <BrandMark size={40} className="mb-6" />
        <h1 className="font-heading text-3xl mb-4">About Tevet-7</h1>
        <p className="text-muted-foreground leading-relaxed mb-6">
          Tevet-7 is a configurable AI agent platform for businesses that need
          to talk to their data. Founded in 2025, we believe every team
          should be able to query their database in plain language without
          waiting for an analyst.
        </p>
        <p className="text-muted-foreground leading-relaxed mb-6">
          Our first tenant is Drive Producteur, a French short-supply-chain
          marketplace. We built an AI agent that lets producers, customers,
          and marketplace admins ask questions in natural language and get
          instant answers with charts and SQL transparency.
        </p>
        <p className="text-muted-foreground leading-relaxed mb-6">
          Tevet-7 is open-source and multi-tenant by design. Each workspace
          has its own schema, roles, and AI agent. Security is enforced at
          the SQL AST level via sqlglot, not by prompting.
        </p>
        <div className="mt-8 pt-8 border-t border-border">
          <a href="/" className="text-sm text-accent hover:underline">← Back to home</a>
        </div>
      </div>
    </div>
  );
}
