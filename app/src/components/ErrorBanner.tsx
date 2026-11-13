import type { RpcErrorData } from "../rpc/types";

export interface ReportedError {
  id: number;
  /** What the user was doing, for example "Connect". */
  context: string;
  error: RpcErrorData;
}

interface Props {
  errors: readonly ReportedError[];
  onDismiss: (id: number) => void;
}

export function ErrorBanner({ errors, onDismiss }: Props) {
  if (errors.length === 0) {
    return null;
  }
  return (
    <section className="errors" aria-live="assertive">
      {errors.map(({ id, context, error }) => (
        <div key={id} className="error" role="alert">
          <div className="error-text">
            <strong>
              {context} failed: {error.message}
            </strong>
            <span>{error.fix}</span>
            <small>
              Code {error.code}
              {error.detail ? ` · ${error.detail}` : ""}
            </small>
          </div>
          <button type="button" onClick={() => onDismiss(id)} aria-label="Dismiss error">
            Dismiss
          </button>
        </div>
      ))}
    </section>
  );
}
