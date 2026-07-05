import { BrandMark } from "@/components/producer-copilot/brand-mark";

export const metadata = { title: "Terms of Service — Tevet-7" };

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-2xl mx-auto px-4 py-20">
        <BrandMark size={40} className="mb-6" />
        <h1 className="font-heading text-3xl mb-4">Terms of Service</h1>
        <p className="text-xs text-muted-foreground mb-8">Last updated: July 2025</p>

        <div className="space-y-6 text-sm text-muted-foreground leading-relaxed">
          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">1. Acceptance of Terms</h2>
            <p>By accessing Tevet-7, you agree to these Terms of Service. If you do not agree, do not use the service.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">2. Description of Service</h2>
            <p>Tevet-7 provides an AI agent platform that allows users to query their databases using natural language. The service includes SQL generation, validation, execution, and response synthesis.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">3. User Accounts</h2>
            <p>You are responsible for maintaining the security of your account credentials. You must provide accurate information during registration.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">4. Acceptable Use</h2>
            <p>You agree not to: (a) attempt to access data belonging to other tenants, (b) use the service for illegal activities, (c) attempt to bypass security measures including SQL injection or prompt injection, (d) reverse engineer the service.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">5. Data Security</h2>
            <p>All SQL queries are validated by sqlglot at the AST level. Row-level security is enforced per tenant. The AI model generates SQL but does not directly access your database. Only metadata (schema structure) is sent to the model.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">6. Limitation of Liability</h2>
            <p>Tevet-7 is provided "as is" without warranties. We are not liable for data loss, business interruption, or inaccurate AI-generated responses.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">7. Termination</h2>
            <p>We may terminate or suspend your account at any time for violation of these terms. You may delete your account at any time.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">8. Changes to Terms</h2>
            <p>We may update these terms. Continued use after changes constitutes acceptance.</p>
          </section>

          <section>
            <h2 className="font-heading text-lg text-foreground mb-2">9. Contact</h2>
            <p>Questions? Email <a href="mailto:hello@tevet7.dev" className="text-accent hover:underline">hello@tevet7.dev</a></p>
          </section>
        </div>

        <div className="mt-8 pt-8 border-t border-border">
          <a href="/" className="text-sm text-accent hover:underline">← Back to home</a>
        </div>
      </div>
    </div>
  );
}
