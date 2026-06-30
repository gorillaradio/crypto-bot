import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { listShareLinks, createShareLink, revokeShareLink, type ShareLink } from "../api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Form,
  FormField,
  FormItem,
  FormControl,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";

const schema = z.object({ label: z.string() });
type Values = z.infer<typeof schema>;

export function ShareLinksModal({ onClose }: { onClose: () => void }) {
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [error, setError] = useState("");
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { label: "" },
  });

  const reload = () => listShareLinks().then(setLinks).catch(() => setError("caricamento fallito"));
  useEffect(() => { reload(); }, []);

  async function onSubmit(values: Values) {
    setError("");
    try {
      await createShareLink(values.label.trim() || undefined);
      form.reset({ label: "" });
      await reload();
    } catch {
      setError("creazione fallita");
    }
  }

  async function revoke(id: number) {
    setError("");
    try {
      await revokeShareLink(id);
      await reload();
    } catch {
      setError("revoca fallita");
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Condividi (sola lettura)</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">Crea link segreti per dare accesso in sola lettura. Ogni link
            è revocabile in qualsiasi momento.</p>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="flex gap-2">
              <FormField control={form.control} name="label" render={({ field }) => (
                <FormItem className="flex-1">
                  <FormControl>
                    <Input placeholder="etichetta (opzionale)" {...field} />
                  </FormControl>
                </FormItem>
              )} />
              <Button type="submit" disabled={form.formState.isSubmitting}>Crea link</Button>
            </form>
          </Form>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <ul className="flex flex-col gap-2">
            {links.map((l) => (
              <li key={l.id} className="flex items-center gap-2">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-sm font-medium">{l.label || "senza etichetta"}</span>
                  <Input readOnly value={l.url}
                    onFocus={(e) => e.currentTarget.select()} />
                </div>
                <Button type="button" variant="outline" size="sm" onClick={() => revoke(l.id)}>revoca</Button>
              </li>
            ))}
            {!links.length && <li className="text-sm text-muted-foreground">Nessun link attivo.</li>}
          </ul>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Chiudi</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
