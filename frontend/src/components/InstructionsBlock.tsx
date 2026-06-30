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
    // original .instructions: margin-top 10px, max-width 75ch
    <div className="mt-[10px] max-w-[75ch]">
      {/*
        Keep class names "instructions-text" and "open" — InstructionsBlock.test.tsx
        queries them directly via document.querySelector(".instructions-text") + .open.
        Tailwind handles the 2-line clamp when NOT open; when open the clamp is lifted.
      */}
      <p
        ref={ref}
        className={`instructions-text text-muted-foreground m-0${open ? " open" : " line-clamp-2"}`}
      >
        {text}
      </p>
      {(overflows || open) && (
        // original .link-toggle: no bg/border, accent color, inherit font, 13px,
        // pt-5px, hover underline
        <button
          className="bg-transparent border-0 text-[color:var(--ef-pos)] cursor-pointer font-[inherit] text-[13px] pt-[5px] p-0 hover:underline"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "mostra meno" : "mostra di più"}
        </button>
      )}
    </div>
  );
}
