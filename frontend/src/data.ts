import { initialWorkspace } from "./workspace";
import type { Project, ProjectStatus } from "./workspace";

export type { Project, ProjectStatus };

export const projects = initialWorkspace.projects;
export const clients = initialWorkspace.clients;
export const activity = initialWorkspace.activity;
