import { BrandMark } from "@/components/producer-copilot/brand-mark";

export const metadata = { title: "Privacy Policy — Tevet-7" };

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-2xl mx-auto px-4 py-20">
        <BrandMark size={40} className="mb-6" />
        <h1 className="font-heading text-3xl mb-4">Privacy Policy</h1>
        <p className="text-xs text-muted-foreground mb-8">Last updated: July 2025</p>

        <div className="space-y-6 text-sm text-muted-foreground leading-relaxed">
          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">1. Data We Collect</h2>
            <p><strong className="text-foreground">Account data:</strong> email, name, password hash (bcrypt).</p>
            <p><strong className="text-foreground">Usage data:</strong> questions asked, SQL generated, latency, token counts. Stored as traces for audit.</p>
            <p><strong className="text-foreground">Tenant data:</strong> schema structure (table names, column names) sent to the AI model. Never the actual data rows.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">2. How We Use Your Data</h2>
            <p>To provide the AI agent service, improve response quality, and ensure security auditability. We do not sell your data.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">3. AI Model Processing</h2>
            <p>When you ask a question, the following is sent to the AI model (OpenAI-compatible provider):</p>
            <ul className="list-disc list-inside mt-2 space-y-1">
              <li>System prompt (schema structure, rules)</li>
              <li>Conversation history (last 10 messages)</li>
              <li>Your question</li>
            </ul>
            <p className="mt-2">Your actual database rows are <strong className="text-foreground">never</strong> sent to the model. SQL is executed locally by the connector after sqlglot validation.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">4. PII Protection</h2>
            <p>The platform includes guardrails that detect and redact personally identifiable information (email, phone, IBAN, SIRET, credit card) before sending to the AI model.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">5. Data Retention</h2>
            <p>Conversation history is stored indefinitely unless you delete it. Traces (audit logs) are retained for security compliance. You can request deletion at any time.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">6. Your Rights (GDPR)</h2>
            <p>You have the right to: access your data, rectify inaccurate data, delete your account and associated data, restrict processing, and data portability. Contact <a href="mailto:hello@tevet7.dev" className="text-accent hover:underline">hello@tevet7.dev</a> to exercise these rights.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">7. Security Measures</h2>
            <p>Row-level security via sqlglot AST rewriting. JWT authentication with refresh tokens. Rate limiting. Prompt injection detection. All passwords hashed with bcrypt.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">8. Contact</h2>
            <p>Privacy questions? Email <a href="mailto:hello@tevet7.dev" className="text-accent hover:underline">hello@tevet7.dev</a></p>
          </section>
        </div>

        <div className="mt-8 pt-8 border-t border-border">
          <a href="/" className="text-sm text-accent hover:underline">← Back to home</a>
        </div>
      </div>
    </div>
  );
}
