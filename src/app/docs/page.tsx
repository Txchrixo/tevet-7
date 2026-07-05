import { BrandMark } from "@/components/producer-copilot/brand-mark";

export const metadata = { title: "Docs - Tevet-7" };

export default function DocsPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-2xl mx-auto px-4 py-20">
        <BrandMark size={40} className="mb-6" />
        <h1 className="font-heading text-3xl mb-4">Documentation</h1>
        <p className="text-muted-foreground leading-relaxed mb-8">
          Full documentation is coming soon on Mintlify. For now, here are
          the key resources:
        </p>

        <div className="space-y-4">
          <a
            href="https://github.com/Txchrixo/tevet-7"
            className="block rounded-lg border border-border bg-card p-4 hover:border-accent/40 transition-colors"
          >
            <h3 className="font-heading text-base text-foreground mb-1">GitHub Repository</h3>
            <p className="text-sm text-muted-foreground">Source code, README, architecture docs, and setup instructions.</p>
          </a>

          <div className="rounded-lg border border-border bg-card p-4">
            <h3 className="font-heading text-base text-foreground mb-2">Quick Start</h3>
            <ol className="list-decimal list-inside text-sm text-muted-foreground space-y-1">
              <li>Create an account</li>
              <li>Create a workspace</li>
              <li>Complete the 4-step onboarding (connect data, detect schema, select tables, define roles)</li>
              <li>Ask questions in natural language</li>
            </ol>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <h3 className="font-heading text-base text-foreground mb-2">Supported LLM Providers</h3>
            <ul className="text-sm text-muted-foreground space-y-1">
              <li>Groq (Llama) - free, 14k req/day</li>
              <li>DeepSeek - paid, high quality</li>
              <li>GLM-4.6 (Z.ai) - free, sandbox</li>
              <li>OpenRouter - aggregator, free models</li>
              <li>Gemini (Google) - free tier</li>
              <li>Any OpenAI-compatible provider</li>
            </ul>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <h3 className="font-heading text-base text-foreground mb-2">Security Model</h3>
            <p className="text-sm text-muted-foreground">
              All SQL is validated by sqlglot at the AST level. Row-level
              scoping is injected deterministically. The AI model never
              touches the database directly.
            </p>
          </div>
        </div>

        <div className="mt-8 pt-8 border-t border-border">
          <a href="/" className="text-sm text-accent hover:underline">← Back to home</a>
        </div>
      </div>
    </div>
  );
}
