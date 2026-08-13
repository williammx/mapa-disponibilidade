// Espelha audit_event_dict em app_v1/serialization.py:139.
export type AuditEvent = {
  id: string;
  actor_user_id: string | null;
  actor_name: string | null;
  organization_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  details: string | null;
  created_at: string;
};

// Chaves conferidas uma a uma nas chamadas audit(...) de app_v1/api.py e
// app_v1/worker.py:164. Acao desconhecida cai no proprio identificador em vez
// de virar texto inventado.
const labels: Record<string, string> = {
  organization_created: "cadastrou um cliente",
  organization_updated: "atualizou o cadastro do cliente",
  organization_user_invited: "convidou um usuario",
  project_created: "criou um projeto",
  project_updated: "atualizou um projeto",
  project_version_published: "publicou uma versao",
  project_version_validated: "rodou a validacao de uma versao",
  processing_job_created: "iniciou um processamento",
  processing_job_succeeded: "concluiu um processamento",
  processing_job_cancelled: "cancelou um processamento",
  file_uploaded: "enviou um arquivo",
  lot_updated: "editou um lote",
  lots_batch_updated: "editou lotes em lote",
  share_link_created: "criou um link de compartilhamento",
  share_link_updated: "atualizou um link de compartilhamento",
  share_link_revoked: "revogou um link de compartilhamento",
  edit_proposal_created: "enviou uma proposta de edicao",
  edit_proposal_accepted: "aceitou uma proposta de edicao",
  edit_proposal_rejected: "recusou uma proposta de edicao",
};

export function auditActionLabel(action: string) {
  return labels[action] ?? `executou ${action}`;
}
