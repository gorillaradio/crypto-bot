import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { deleteAgent, type Agent } from "../api";
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
  FormLabel,
  FormControl,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";

type Props = { agent: Agent; onClose: () => void; onDeleted: (id: number) => void };

export function ConfirmDeleteModal({ agent, onClose, onDeleted }: Props) {
  const schema = useMemo(
    () =>
      z.object({
        confirmText: z.string().refine((v) => v === agent.name, "il nome non corrisponde"),
      }),
    [agent.name]
  );
  type Values = z.infer<typeof schema>;

  const [error, setError] = useState("");
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { confirmText: "" },
  });
  const matches = schema.safeParse(form.watch()).success;

  async function onSubmit() {
    setError("");
    try {
      await deleteAgent(agent.id);
      onDeleted(agent.id);
    } catch {
      setError("eliminazione fallita");
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Elimina «{agent.name}»</DialogTitle>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">Questa azione è irreversibile. Verranno cancellati definitivamente posizioni,
              operazioni, equity, eventi e memoria di questo agente.</p>
            <FormField control={form.control} name="confirmText" render={({ field }) => (
              <FormItem>
                <FormLabel>Scrivi <b>{agent.name}</b> per confermare</FormLabel>
                <FormControl>
                  <Input autoFocus {...field} />
                </FormControl>
              </FormItem>
            )} />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Annulla</Button>
              <Button type="submit" variant="destructive" disabled={!matches || form.formState.isSubmitting}>Elimina</Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
