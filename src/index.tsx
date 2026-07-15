import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  SliderField,
  staticClasses,
  TextField,
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
import {
  FaArchive,
  FaGoogleDrive,
  FaHdd,
  FaSdCard,
  FaTrash,
  FaUndo,
} from "react-icons/fa";

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
  auto?: boolean;
  location: "internal" | "sd" | "gdrive";
}

interface Schedule {
  enabled: boolean;
  frequency: "daily" | "weekly";
  dest_id: string;
  keep: number;
  include_data: boolean;
  last_run: number;
}

interface AutoBackupEvent {
  success: boolean;
  size?: number;
  dest?: string;
  warning?: string | null;
  pruned?: number;
  error?: string;
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

interface RestoreSelection {
  everything: boolean;
  themes: boolean;
  plugins: string[];
}

interface InspectResult {
  success: boolean;
  error?: string;
  plugins?: string[];
  themes?: string[];
  manifest?: { created?: string; plugins?: PluginRef[] };
}

interface RestoreResult {
  success: boolean;
  error?: string;
  missing_plugins?: PluginRef[];
}

interface GDriveStatus {
  has_client: boolean;
  connected: boolean;
}

interface AuthStart {
  success: boolean;
  error?: string;
  user_code?: string;
  verification_url?: string;
  interval?: number;
}

const getDestinations = callable<[], Destination[]>("get_destinations");
const getSizeEstimate = callable<[components: string[]], number>("get_size_estimate");
const createBackup = callable<[components: string[], destPath: string], BackupResult>("create_backup");
const listBackups = callable<[], BackupEntry[]>("list_backups");
const inspectBackup = callable<[archivePath: string], InspectResult>("inspect_backup");
const restoreBackup = callable<[archivePath: string, selection: RestoreSelection], RestoreResult>("restore_backup");
const deleteBackup = callable<[archivePath: string], BackupResult>("delete_backup");
const gdriveStatus = callable<[], GDriveStatus>("gdrive_status");
const gdriveSetClient = callable<[clientId: string, clientSecret: string], BackupResult>("gdrive_set_client");
const gdriveAuthStart = callable<[], AuthStart>("gdrive_auth_start");
const gdriveAuthPoll = callable<[], { status: string; error?: string }>("gdrive_auth_poll");
const gdriveDisconnect = callable<[], BackupResult>("gdrive_disconnect");
const getSchedule = callable<[], Schedule>("get_schedule");
const setSchedule = callable<[patch: Partial<Schedule>], Schedule>("set_schedule");

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

function locationIcon(location: BackupEntry["location"]) {
  if (location === "gdrive") return <FaGoogleDrive />;
  if (location === "sd") return <FaSdCard />;
  return <FaHdd />;
}

function locationLabel(location: BackupEntry["location"]) {
  if (location === "gdrive") return "Google Drive";
  if (location === "sd") return "SD card";
  return "internal";
}

function RestoreModal({
  backup,
  onDone,
  closeModal,
}: {
  backup: BackupEntry;
  onDone: () => void;
  closeModal?: () => void;
}) {
  const [info, setInfo] = useState<InspectResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [everything, setEverything] = useState(true);
  const [themes, setThemes] = useState(true);
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  useEffect(() => {
    inspectBackup(backup.path).then((result) => {
      if (result.success) {
        setInfo(result);
        setSelected(Object.fromEntries((result.plugins ?? []).map((p) => [p, true])));
      } else {
        setError(result.error ?? "Could not read backup");
      }
    });
  }, [backup.path]);

  const runRestore = async () => {
    const selection: RestoreSelection = {
      everything,
      themes,
      plugins: Object.keys(selected).filter((k) => selected[k]),
    };
    const result = await restoreBackup(backup.path, selection);
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
    onDone();
  };

  return (
    <ConfirmModal
      strTitle="Restore backup"
      strDescription={`${backup.name} · ${formatDate(backup.mtime)}. Restored files overwrite current ones; restart Decky Loader afterwards.`}
      strOKButtonText="Restore"
      bOKDisabled={!info}
      onCancel={closeModal}
      onOK={() => {
        runRestore();
        closeModal?.();
      }}
    >
      {!info && !error && (
        <Field
          label={
            backup.location === "gdrive"
              ? "Downloading from Google Drive…"
              : "Reading backup…"
          }
        />
      )}
      {error && <Field label="Error" description={error} />}
      {info && (
        <>
          <ToggleField
            label="Restore everything"
            checked={everything}
            onChange={setEverything}
          />
          {!everything && (
            <>
              {(info.themes?.length ?? 0) > 0 && (
                <ToggleField
                  label={`CSS themes (${info.themes!.length})`}
                  checked={themes}
                  onChange={setThemes}
                />
              )}
              {(info.plugins ?? []).map((p) => (
                <ToggleField
                  key={p}
                  label={p}
                  checked={selected[p] ?? false}
                  onChange={(value) =>
                    setSelected((prev) => ({ ...prev, [p]: value }))
                  }
                />
              ))}
              {(info.plugins?.length ?? 0) === 0 && (
                <Field label="No per-plugin data found in this backup" />
              )}
            </>
          )}
        </>
      )}
    </ConfirmModal>
  );
}

function GDriveAuthModal({
  onDone,
  closeModal,
}: {
  onDone: () => void;
  closeModal?: () => void;
}) {
  const [info, setInfo] = useState<AuthStart | null>(null);
  const [status, setStatus] = useState("Starting…");

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    (async () => {
      const start = await gdriveAuthStart();
      if (stopped) return;
      if (!start.success) {
        setStatus(start.error ?? "Could not start authorization");
        return;
      }
      setInfo(start);
      setStatus("Waiting for approval…");
      const interval = (start.interval ?? 5) * 1000;
      const poll = async () => {
        if (stopped) return;
        const result = await gdriveAuthPoll();
        if (stopped) return;
        if (result.status === "connected") {
          toaster.toast({
            title: "Google Drive connected",
            body: "Google Drive is now available as a backup destination.",
          });
          onDone();
          closeModal?.();
        } else if (result.status === "pending") {
          timer = setTimeout(poll, interval);
        } else {
          setStatus(result.error ?? "Authorization failed");
        }
      };
      timer = setTimeout(poll, interval);
    })();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);

  return (
    <ConfirmModal
      strTitle="Connect Google Drive"
      strOKButtonText="Waiting…"
      bOKDisabled
      onCancel={closeModal}
    >
      <Field
        label="1. On your phone or PC, open:"
        description={info?.verification_url ?? "…"}
      />
      <Field label="2. Enter this code:">
        <div
          style={{
            fontSize: "1.6em",
            fontWeight: 700,
            letterSpacing: "0.15em",
            textAlign: "center",
          }}
        >
          {info?.user_code ?? "…"}
        </div>
      </Field>
      <div className={staticClasses.Label}>{status}</div>
    </ConfirmModal>
  );
}

function GDriveClientModal({
  onSaved,
  closeModal,
}: {
  onSaved: () => void;
  closeModal?: () => void;
}) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  return (
    <ConfirmModal
      strTitle="Google OAuth client"
      strOKButtonText="Save"
      bOKDisabled={clientId.trim() === "" || clientSecret.trim() === ""}
      onCancel={closeModal}
      onOK={async () => {
        await gdriveSetClient(clientId.trim(), clientSecret.trim());
        closeModal?.();
        onSaved();
      }}
    >
      <Field description="One-time setup: create a free OAuth client in Google Cloud Console (type: 'TVs and Limited Input devices') with the Drive API enabled, then paste it here. The README has a 2-minute walkthrough. Credentials stay on this device." />
      <TextField
        label="Client ID"
        value={clientId}
        onChange={(e) => setClientId(e.target.value)}
      />
      <TextField
        label="Client secret"
        value={clientSecret}
        onChange={(e) => setClientSecret(e.target.value)}
      />
    </ConfirmModal>
  );
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
  const [gdrive, setGdrive] = useState<GDriveStatus | null>(null);
  const [schedule, setScheduleState] = useState<Schedule | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);

  const selectedComponents = COMPONENTS.map((c) => c.key).filter((k) => enabled[k]);

  const refresh = useCallback(async () => {
    const [dests, list, status, sched] = await Promise.all([
      getDestinations(),
      listBackups(),
      gdriveStatus(),
      getSchedule(),
    ]);
    setDestinations(dests);
    setBackups(list);
    setGdrive(status);
    setScheduleState(sched);
    if (!dests.some((d) => d.id === destId)) setDestId("internal");
  }, [destId]);

  const patchSchedule = async (patch: Partial<Schedule>) => {
    setScheduleState(await setSchedule(patch));
  };

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const listener = addEventListener<[stage: string]>("backup_progress", (s) => {
      setStage(s);
    });
    return () => removeEventListener("backup_progress", listener);
  }, []);

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
    showModal(<RestoreModal backup={backup} onDone={refresh} />);
  };

  const onDelete = (backup: BackupEntry) => {
    showModal(
      <ConfirmModal
        strTitle="Delete backup?"
        strDescription={`Delete ${backup.name} (${formatSize(backup.size)}) from ${locationLabel(backup.location)}? This cannot be undone.`}
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

  const onConnectGdrive = () => {
    if (!gdrive?.has_client) {
      showModal(
        <GDriveClientModal
          onSaved={() => showModal(<GDriveAuthModal onDone={refresh} />)}
        />
      );
    } else {
      showModal(<GDriveAuthModal onDone={refresh} />);
    }
  };

  const onDisconnectGdrive = () => {
    showModal(
      <ConfirmModal
        strTitle="Disconnect Google Drive?"
        strDescription="Backups already on Drive stay there; they just won't show in the list until you reconnect."
        strOKButtonText="Disconnect"
        onOK={async () => {
          await gdriveDisconnect();
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
                  {locationIcon(b.location)}
                  {formatDate(b.mtime)}
                </span>
              }
              description={`${formatSize(b.size)} · ${locationLabel(b.location)}${b.auto ? " · auto" : ""}`}
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

      <PanelSection title="Automatic backups">
        <PanelSectionRow>
          <ToggleField
            label="Enabled"
            description={
              schedule?.enabled && schedule.last_run > 0
                ? `Last run: ${formatDate(schedule.last_run)}`
                : "Runs in the background while the Deck is awake"
            }
            checked={schedule?.enabled ?? false}
            onChange={(value) => patchSchedule({ enabled: value })}
          />
        </PanelSectionRow>
        {schedule?.enabled && (
          <>
            <PanelSectionRow>
              <DropdownItem
                label="Frequency"
                rgOptions={[
                  { data: "daily", label: "Daily" },
                  { data: "weekly", label: "Weekly" },
                ]}
                selectedOption={schedule.frequency}
                onChange={(option) =>
                  patchSchedule({ frequency: option.data as Schedule["frequency"] })
                }
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem
                label="Destination"
                description="Falls back to internal storage if unavailable"
                rgOptions={destinations.map((d) => ({ data: d.id, label: d.label }))}
                selectedOption={
                  destinations.some((d) => d.id === schedule.dest_id)
                    ? schedule.dest_id
                    : "internal"
                }
                onChange={(option) => patchSchedule({ dest_id: option.data as string })}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <SliderField
                label="Keep last"
                description="Older automatic backups are deleted; manual backups are never touched"
                value={schedule.keep}
                min={1}
                max={20}
                step={1}
                showValue
                onChange={(value) => patchSchedule({ keep: value })}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label="Include plugin data"
                description="Runtime data — can be large"
                checked={schedule.include_data}
                onChange={(value) => patchSchedule({ include_data: value })}
              />
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <PanelSection title="Google Drive">
        <PanelSectionRow>
          <Field
            label={
              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <FaGoogleDrive />
                {gdrive?.connected ? "Connected" : "Not connected"}
              </span>
            }
            description={
              gdrive?.connected
                ? "Backups can be saved to and restored from your Drive."
                : "Connect to back up to the cloud. Uses drive.file scope — the plugin only sees its own files."
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          {gdrive?.connected ? (
            <ButtonItem layout="below" disabled={busy} onClick={onDisconnectGdrive}>
              Disconnect
            </ButtonItem>
          ) : (
            <ButtonItem layout="below" disabled={busy} onClick={onConnectGdrive}>
              Connect Google Drive
            </ButtonItem>
          )}
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  // Registered at plugin level so scheduled-backup toasts appear even
  // when the QAM panel is closed.
  const autoListener = addEventListener<[result: AutoBackupEvent]>(
    "auto_backup",
    (result) => {
      if (result.success) {
        toaster.toast({
          title: "Automatic backup complete",
          body: `${formatSize(result.size ?? 0)} saved to ${result.dest ?? "internal storage"}${
            result.warning ? ` (${result.warning})` : ""
          }`,
        });
      } else {
        toaster.toast({
          title: "Automatic backup failed",
          body: result.error ?? "Unknown error",
        });
      }
    }
  );

  return {
    name: "Deck Backup",
    titleView: <div className={staticClasses.Title}>Deck Backup</div>,
    content: <Content />,
    icon: <FaArchive />,
    onDismount() {
      removeEventListener("auto_backup", autoListener);
    },
  };
});
