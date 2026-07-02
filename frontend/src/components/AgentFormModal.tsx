import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { createAgent, updateAgent, type Agent } from "../api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Props =
  | { mode: "create"; onClose: () => void; onSaved: (a: Agent) => void }
  | { mode: "edit"; agent: Agent; onClose: () => void; onSaved: (a: Agent) => void };

type FormValues = {
  name: string;
  instructions: string;
  durationDays: number;
  modelName: string;
  universe: "TOP_50" | "TOP_100";
  stopLoss: number | null;
  takeProfit: number | null;
};

export function AgentFormModal(props: Props) {
  const isEdit = props.mode === "edit";
  // One schema whose output is always FormValues; the create-only requirements
  // (duration, model) are enforced conditionally so edit can rename name only.
  const schema = z
    .object({
      name: z.string().trim().min(1, "il nome è obbligatorio"),
      instructions: z.string(),
      durationDays: z.number(),
      modelName: z.string().trim(),
      universe: z.enum(["TOP_50", "TOP_100"]),
      stopLoss: z.number().gt(0).lt(100).nullable(),
      takeProfit: z.number().gt(0).max(500).nullable(),
    })
    .superRefine((v, ctx) => {
      if (isEdit) return;
      if (v.durationDays < 1)
        ctx.addIssue({ code: "custom", path: ["durationDays"], message: "minimo 1 giorno" });
      if (v.modelName.length < 1)
        ctx.addIssue({ code: "custom", path: ["modelName"], message: "il modello è obbligatorio" });
    });

  const [error, setError] = useState("");
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: isEdit ? props.agent.name : "",
      instructions: "",
      durationDays: 7,
      modelName: "",
      universe: "TOP_100",
      stopLoss: 10,
      takeProfit: 20,
    },
  });
  const valid = schema.safeParse(form.watch()).success;

  async function onSubmit(values: FormValues) {
    setError("");
    try {
      if (isEdit) {
        const a = await updateAgent(props.agent.id, { name: values.name });
        props.onSaved(a);
      } else {
        const a = await createAgent({
          name: values.name,
          instructions: values.instructions,
          duration_days: values.durationDays,
          model_name: values.modelName,
          universe: values.universe,
          stop_loss: values.stopLoss == null ? null : values.stopLoss / 100,
          take_profit: values.takeProfit == null ? null : values.takeProfit / 100,
        });
        props.onSaved(a);
      }
    } catch {
      setError(isEdit ? "modifica fallita" : "creazione fallita");
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) props.onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Modifica agente" : "Nuovo agente"}</DialogTitle>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-3">
            <FormField control={form.control} name="name" render={({ field }) => (
              <FormItem>
                <FormLabel>Nome</FormLabel>
                <FormControl>
                  <Input autoFocus {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )} />

            {!isEdit && (
              <>
                <FormField control={form.control} name="instructions" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Istruzioni</FormLabel>
                    <FormControl>
                      <Textarea rows={3} {...field} />
                    </FormControl>
                  </FormItem>
                )} />

                <FormField control={form.control} name="durationDays" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Durata (giorni)</FormLabel>
                    <FormControl>
                      <Input type="number" min={1} {...field}
                        onChange={(e) => field.onChange(Number(e.target.value))} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )} />

                <FormField control={form.control} name="modelName" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Modello (OpenRouter)</FormLabel>
                    <FormControl>
                      <Input placeholder="es. deepseek/deepseek-v4-flash" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )} />

                <FormField control={form.control} name="universe" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Universo</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="TOP_100">Top 100</SelectItem>
                        <SelectItem value="TOP_50">Top 50</SelectItem>
                      </SelectContent>
                    </Select>
                  </FormItem>
                )} />

                <FormField control={form.control} name="stopLoss" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Stop-loss (%) — vuoto = disattivato</FormLabel>
                    <FormControl>
                      <Input type="number" min={0} step="any" value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value === "" ? null : Number(e.target.value))} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )} />

                <FormField control={form.control} name="takeProfit" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Take-profit (%) — vuoto = disattivato</FormLabel>
                    <FormControl>
                      <Input type="number" min={0} step="any" value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value === "" ? null : Number(e.target.value))} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )} />
              </>
            )}

            {isEdit && (
              <p className="text-sm text-muted-foreground">Solo il nome è modificabile: gli altri parametri
                definiscono il comportamento e restano fissi per l'intera run.</p>
            )}

            {error && <p className="text-sm text-destructive">{error}</p>}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={props.onClose}>Annulla</Button>
              <Button type="submit" disabled={!valid || form.formState.isSubmitting}>
                {isEdit ? "Salva" : "Crea"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
