import { BrandMark } from "@/components/producer-copilot/brand-mark";

export const metadata = { title: "Contact - Tevet-7" };

export default function ContactPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-2xl mx-auto px-4 py-20">
        <BrandMark size={40} className="mb-6" />
        <h1 className="font-heading text-3xl mb-4">Contact us</h1>
        <p className="text-muted-foreground leading-relaxed mb-8">
          Have a question? Want a demo? Need help with setup?
          We reply within 24 hours.
        </p>
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium text-foreground mb-1">Email</h3>
            <a href="mailto:hello@tevet7.dev" className="text-sm text-accent hover:underline">hello@tevet7.dev</a>
          </div>
          <div>
            <h3 className="text-sm font-medium text-foreground mb-1">GitHub</h3>
            <a href="https://github.com/Txchrixo/tevet-7" className="text-sm text-accent hover:underline">github.com/Txchrixo/tevet-7</a>
          </div>
          <div>
            <h3 className="text-sm font-medium text-foreground mb-1">Response time</h3>
            <p className="text-sm text-muted-foreground">Within 24 hours, Monday to Friday.</p>
          </div>
        </div>
        <div className="mt-8 pt-8 border-t border-border">
          <a href="/" className="text-sm text-accent hover:underline">← Back to home</a>
        </div>
      </div>
    </div>
  );
}
