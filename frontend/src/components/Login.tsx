import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { login } from "../api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

const schema = z.object({ password: z.string().min(1, "inserisci la password") });
type Values = z.infer<typeof schema>;

export function Login({ onAuthed }: { onAuthed: () => void }) {
  const [error, setError] = useState("");
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { password: "" },
  });

  async function onSubmit(values: Values) {
    setError("");
    try {
      const { role } = await login(values.password);
      if (role === "admin") onAuthed();
      else setError("password errata");
    } catch {
      setError("password errata");
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <span>crypto<b>·</b>bot</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-3">
            <div className="grid gap-2">
              <Label htmlFor="login-password">Password</Label>
              <Input id="login-password" type="password" autoFocus
                aria-invalid={!!form.formState.errors.password}
                {...form.register("password")} />
              {form.formState.errors.password && (
                <p className="text-sm text-destructive">{form.formState.errors.password.message}</p>
              )}
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={form.formState.isSubmitting}>Entra</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
