// O backend serializa datas com datetime.isoformat() sobre valores gerados por
// models.utcnow(), que usa datetime.utcnow() e portanto nao carrega fuso. Sem
// marcar o "Z" o navegador leria o horario como local e mostraria a hora errada.
function asUtcDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /(Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string {
  const date = asUtcDate(value);
  if (!date) return "";
  return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function isPastDate(value: string | null | undefined): boolean {
  const date = asUtcDate(value);
  return Boolean(date && date.getTime() <= Date.now());
}

// Valor para <input type="datetime-local">, que so aceita horario local sem fuso.
export function toLocalInputValue(value: string | null | undefined): string {
  const date = asUtcDate(value);
  if (!date) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// Caminho inverso: o operador escolhe no fuso dele e o backend compara com
// datetime.utcnow() ingenuo, entao enviamos o instante em UTC sem sufixo. Mandar
// com "Z" criaria um datetime com fuso e a comparacao no servidor quebraria.
export function toApiDateTime(localValue: string): string | null {
  if (!localValue) return null;
  const date = new Date(localValue);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString().slice(0, 19);
}
