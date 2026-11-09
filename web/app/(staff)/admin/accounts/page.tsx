"use client";

/**
 * Staff and parent accounts (ARCHITECTURE.md §5.1, §7).
 *
 * §5.1: accounts are created here and never self-registered. A new account
 * gets a temporary password shown **once** — it is not stored readably, not
 * logged and not audited — so this screen is deliberate about making the
 * admin acknowledge it before it disappears.
 *
 * Attaching children to a parent is `/admin/accounts/[userId]` (D104). It is
 * the record §5.2's most important filter rests on — a parent sees exactly
 * the pupils named there and no others — and it belongs on a page of its own
 * rather than unfolding under a table of forty accounts.
 */

import { KeyRound, Plus, UserPlus, Users } from "lucide-react";
import { useState } from "react";

import { Modal } from "@/components/modal";
import {
  Avatar,
  Badge,
  Button,
  ButtonLink,
  Cell,
  Field,
  Input,
  Notice,
  OneTimeSecret,
  PageHeader,
  Panel,
  Row,
  Select,
  SkeletonTable,
  Table,
} from "@/components/ui";
import type { CreatedAccount, Role } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDateTime, ROLE_LABELS } from "@/lib/format";
import { useAction, useResource } from "@/lib/use-async";

const ROLES: Role[] = ["admin", "head_teacher", "teacher", "parent"];

export default function AccountsPage() {
  const api = useAdminApi();
  const [filterRole, setFilterRole] = useState<"" | Role>("");
  const accounts = useResource(
    () => api!.users(filterRole || undefined),
    [api, filterRole],
    { enabled: Boolean(api) },
  );

  const [secret, setSecret] = useState<CreatedAccount | null>(null);
  // Which row's reset is running, so only that button spins.
  const [resetting, setResetting] = useState<string | null>(null);

  const action = useAction(accounts.reload);
  // Its own action, so a failed create shows in the dialog and a failed
  // reset shows on the page — never one in the other's place.
  const create = useAction(accounts.reload);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    role: "teacher" as Role,
    full_name: "",
    email: "",
    phone: "",
  });

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Nobody can register themselves. Every account starts here."
        actions={
          <Button
            icon={UserPlus}
            disabled={!api}
            onClick={() => {
              create.clear();
              setCreating(true);
            }}
          >
            Create account
          </Button>
        }
      />

      {secret ? (
        <OneTimeSecret value={secret.temporary_password} onDismiss={() => setSecret(null)}>
          Temporary password for {secret.user.full_name}
        </OneTimeSecret>
      ) : null}

      <Notice>{action.error}</Notice>

      <Panel
        title="Everyone with an account"
        icon={Users}
        actions={
          <div className="w-44">
            <Field label="Role">
              <Select
                value={filterRole}
                onChange={(event) => setFilterRole(event.target.value as "" | Role)}
              >
                <option value="">Everyone</option>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABELS[role]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        }
      >
        {!api || accounts.loading ? (
          <SkeletonTable rows={8} columns={5} label="Loading the accounts…" />
        ) : (
          <>
            {accounts.error ? <Notice>{accounts.error}</Notice> : null}

            <Table
              head={["Name", "Role", "Signs in with", "Last signed in", ""]}
              empty="No accounts."
            >
              {(accounts.data ?? []).map((account) => (
                <Row key={account.id}>
                  <Cell>
                    <span className="flex items-center gap-2.5">
                      <Avatar name={account.full_name} size="sm" />
                      <span className="min-w-0">
                        <span className="block font-medium">{account.full_name}</span>
                        <span className="flex flex-wrap gap-1">
                          {account.must_change_password ? (
                            <Badge tone="warn">Password not changed</Badge>
                          ) : null}
                          {account.is_active ? null : <Badge tone="bad">Deactivated</Badge>}
                        </span>
                      </span>
                    </span>
                  </Cell>
                  <Cell className="text-[var(--muted)]">
                    {ROLE_LABELS[account.role] ?? account.role}
                  </Cell>
                  <Cell className="text-[var(--muted)]">
                    {account.email ?? account.phone ?? "—"}
                  </Cell>
                  <Cell className="text-[var(--muted)]">
                    {formatDateTime(account.last_login_at)}
                  </Cell>
                  <Cell className="whitespace-nowrap text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={KeyRound}
                      loading={resetting === account.id}
                      disabled={action.busy}
                      onClick={async () => {
                        setResetting(account.id);
                        await action.run(async () => {
                          setSecret(await api!.resetPassword(account.id));
                        });
                        setResetting(null);
                      }}
                    >
                      Reset password
                    </Button>
                    {account.role === "parent" ? (
                      <ButtonLink
                        href={`/admin/accounts/${account.id}`}
                        size="sm"
                        className="ml-1.5"
                      >
                        Children
                      </ButtonLink>
                    ) : null}
                  </Cell>
                </Row>
              ))}
            </Table>
          </>
        )}
      </Panel>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="Create an account"
        description="An email address or a phone number — either one signs in, against the same password."
      >
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await create.run(async () => {
              setSecret(
                await api!.createUser({
                  role: form.role,
                  full_name: form.full_name,
                  email: form.email || null,
                  phone: form.phone || null,
                }),
              );
            });
            if (created) {
              setForm({ ...form, full_name: "", email: "", phone: "" });
              // Closed so the one-time password above is what they see next.
              setCreating(false);
            }
          }}
        >
          <Field label="Role" required>
            <Select
              value={form.role}
              onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Full name" hint="Printed on the report card." required>
            <Input
              required
              value={form.full_name}
              onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            />
          </Field>
          <Field label="Email address">
            <Input
              type="email"
              autoCapitalize="none"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
            />
          </Field>
          <Field
            label="Phone number"
            hint="Many parents' email addresses are inactive; a phone number is enough."
          >
            <Input
              inputMode="tel"
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
            />
          </Field>
          {create.error ? (
            <div className="sm:col-span-2">
              <Notice>{create.error}</Notice>
            </div>
          ) : null}
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="secondary" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button type="submit" icon={Plus} loading={create.busy} disabled={!api}>
              Create account
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
