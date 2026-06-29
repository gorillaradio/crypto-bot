import { useLayoutEffect, useRef, useState } from "react";

// The agent's instructions can run long; collapsed to two lines by default with a
// toggle that only appears when the text actually overflows.
export function InstructionsBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const ref = useRef<HTMLParagraphElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Measured while collapsed (clamp active), so scrollHeight is the full text.
    setOverflows(el.scrollHeight - el.clientHeight > 2);
  }, [text]);

  return (
    <div className="instructions">
      <p ref={ref} className={`instructions-text${open ? " open" : ""}`}>
        {text}
      </p>
      {(overflows || open) && (
        <button
          className="link-toggle"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "mostra meno" : "mostra di più"}
        </button>
      )}
    </div>
  );
}
