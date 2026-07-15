import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  staticClasses,
  ToggleField,
} from "@decky/ui";
import {
  addEventListener,
  callable,
  definePlugin,
  removeEventListener,
  toaster,
} from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaArchive, FaSdCard, FaHdd, FaTrash, FaUndo } from "react-icons/fa";

interface Destination {
  id: string;
  label: string;
  path: string;
}

interface BackupEntry {
  path: string;
  name: string;
  size: number;
  mtime: number;
  location: "internal" | "sd";
}

interface PluginRef {
  dir: string;
  name: string;
  version: string | null;
}

interface BackupResult {
  success: boolean;
  error?: string;
  path?: string;
  size?: number;
}

interface RestoreResult {
  success: boolean;
  error?: string;
  missing_plugins?: PluginRef[];
}

const getDestinations = callable<[], Destination[]>("get_destinations");
const getSizeEstimate = callable<[components: string[]], number>("get_size_estimate");
const createBackup = callable<[components: string[], destPath: string], BackupResult>("create_backup");
const listBackups = callable<[], BackupEntry[]>("list_backups");
const restoreBackup = callable<[archivePath: string, components: string[]], RestoreResult>("restore_backup");
const deleteBackup = callable<[archivePath: string], BackupResult>("delete_backup");

const COMPONENTS = [
  { key: "settings", label: "Plugin settings", note: "All plugin configs (PowerTools profiles, etc.)" },
  { key: "themes", label: "CSS themes", note: "CSS Loader themes" },
  { key: "data", label: "Plugin data", note: "Runtime data — can be large" },
];

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function formatDate(mtime: number): string {
  return new Date(mtime * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function Content() {
  const [enabled, setEnabled] = useState<Record<string, boolean>>({
    settings: true,
    themes: true,
    data: false,
  });
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [destId, setDestId] = useState<string>("internal");
  const [estimate, setEstimate] = useState<number | null>(null);
  const [backups, setBackups] = useState<BackupEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);

  const selectedComponents = COMPONENTS.map((c) => c.key).filter((k) => enabled[k]);

  const refresh = useCallback(async () => {
    const [dests, list] = await Promise.all([getDestinations(), listBackups()]);
    setDestinations(dests);
    setBackups(list);
    if (!dests.some((d) => d.id === destId)) setDestId("internal");
  }, [destId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    if (selectedComponents.length === 0) {
      setEstimate(null);
      return;
    }
    getSizeEstimate(selectedComponents).then((size) => {
      if (!cancelled) setEstimate(size);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const onBackup = async () => {
    const dest = destinations.find((d) => d.id === destId);
    if (!dest || selectedComponents.length === 0) return;
    setBusy(true);
    setStage("Starting…");
    try {
      const result = await createBackup(selectedComponents, dest.path);
      if (result.success) {
        toaster.toast({
          title: "Backup complete",
          body: `${formatSize(result.size ?? 0)} saved to ${dest.label}`,
        });
      } else {
        toaster.toast({ title: "Backup failed", body: result.error ?? "Unknown error" });
      }
    } finally {
      setBusy(false);
      setStage(null);
      refresh();
    }
  };

  const onRestore = (backup: BackupEntry) => {
    showModal(
      <ConfirmModal
        strTitle="Restore backup?"
        strDescription={`Restore ${backup.name} from ${formatDate(backup.mtime)}? Current plugin settings and themes will be overwritten. A restart of Decky Loader (or the Deck) is recommended afterwards.`}
        strOKButtonText="Restore"
        onOK={async () => {
          setBusy(true);
          setStage("Restoring…");
          try {
            const result = await restoreBackup(backup.path, ["settings", "themes", "data"]);
            if (result.success) {
              const missing = result.missing_plugins ?? [];
              toaster.toast({
                title: "Restore complete",
                body:
                  missing.length > 0
                    ? `Reinstall from store: ${missing.map((p) => p.name).join(", ")}`
                    : "Restart Decky Loader to apply.",
                duration: 8000,
              });
            } else {
              toaster.toast({ title: "Restore failed", body: result.error ?? "Unknown error" });
            }
          } finally {
            setBusy(false);
            setStage(null);
          }
        }}
      />
    );
  };

  const onDelete = (backup: BackupEntry) => {
    showModal(
      <ConfirmModal
        strTitle="Delete backup?"
        strDescription={`Delete ${backup.name} (${formatSize(backup.size)})? This cannot be undone.`}
        strOKButtonText="Delete"
        onOK={async () => {
          const result = await deleteBackup(backup.path);
          if (!result.success) {
            toaster.toast({ title: "Delete failed", body: result.error ?? "Unknown error" });
          }
          refresh();
        }}
      />
    );
  };

  return (
    <>
      <PanelSection title="New backup">
        {COMPONENTS.map((c) => (
          <PanelSectionRow key={c.key}>
            <ToggleField
              label={c.label}
              description={c.note}
              checked={enabled[c.key]}
              onChange={(value) => setEnabled((prev) => ({ ...prev, [c.key]: value }))}
            />
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <DropdownItem
            label="Destination"
            rgOptions={destinations.map((d) => ({ data: d.id, label: d.label }))}
            selectedOption={destId}
            onChange={(option) => setDestId(option.data as string)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy || selectedComponents.length === 0}
            onClick={onBackup}
          >
            {busy
              ? stage ?? "Working…"
              : `Back up now${estimate !== null ? ` (~${formatSize(estimate)})` : ""}`}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={`Backups (${backups.length})`}>
        {backups.length === 0 && (
          <PanelSectionRow>
            <Field label="No backups yet" description="Create one above — it takes a few seconds." />
          </PanelSectionRow>
        )}
        {backups.map((b) => (
          <PanelSectionRow key={b.path}>
            <Field
              label={
                <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  {b.location === "sd" ? <FaSdCard /> : <FaHdd />}
                  {formatDate(b.mtime)}
                </span>
              }
              description={`${formatSize(b.size)} · ${b.location === "sd" ? "SD card" : "internal"}`}
            >
              <div style={{ display: "flex", gap: "8px" }}>
                <ButtonItem layout="inline" disabled={busy} onClick={() => onRestore(b)}>
                  <FaUndo />
                </ButtonItem>
                <ButtonItem layout="inline" disabled={busy} onClick={() => onDelete(b)}>
                  <FaTrash />
                </ButtonItem>
              </div>
            </Field>
          </PanelSectionRow>
        ))}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  const progressListener = addEventListener<[stage: string]>("backup_progress", (stage) => {
    console.log("Deck Backup progress:", stage);
  });

  return {
    name: "Deck Backup",
    titleView: <div className={staticClasses.Title}>Deck Backup</div>,
    content: <Content />,
    icon: <FaArchive />,
    onDismount() {
      removeEventListener("backup_progress", progressListener);
    },
  };
});
