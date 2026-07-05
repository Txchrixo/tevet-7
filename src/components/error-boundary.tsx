"use client";

import { Component, ErrorInfo, ReactNode } from "react";
import { RefreshCw, AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("[ErrorBoundary] caught error:", error, errorInfo);
  }

  handleReload = (): void => {
    this.setState({ hasError: false, error: null });
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="flex min-h-screen items-center justify-center bg-background p-4">
          <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
              <AlertTriangle className="h-6 w-6 text-destructive" />
            </div>
            <h2 className="mb-2 font-heading text-xl text-foreground">
              Une erreur est survenue
            </h2>
            <p className="mb-4 text-sm text-muted-foreground">
              L&apos;application a rencontré une erreur inattendue. Vous pouvez
              recharger la page pour réessayer.
            </p>
            {this.state.error && (
              <details className="mb-4 rounded border border-border bg-muted/20 p-2 text-left">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  Détails techniques
                </summary>
                <pre className="mt-2 overflow-x-auto text-[10px] text-muted-foreground">
                  {this.state.error.message}
                </pre>
              </details>
            )}
            <button
              onClick={this.handleReload}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <RefreshCw className="h-4 w-4" />
              Recharger la page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
