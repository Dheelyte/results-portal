"use client";

/**
 * Staff and parent accounts (ARCHITECTURE.md §5.1, §7).
 *
 * §5.1: accounts are created here and never self-registered. A new account
 * gets a temporary password shown **once** — it is not stored readably, not
 * logged and not audited — so this screen is deliberate about making the
 * admin acknowledge it before it disappears.
 *
 * Attaching children to a parent is the record §5.2's most important filter
 * rests on: a parent sees exactly the pupils named there and no others.
 */

import { useState } from "react";

import {
  Badge,
  Button,
  Cell,
  Field,
  Input,
  Notice,
  OneTimeSecret,
  Panel,
  Row,
  Select,
  Spinner,
  Table,
} from "@/components/ui";
import type { Account, CreatedAccount, Role } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDateTime, pupilName, ROLE_LABELS } from "@/lib/format";
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
  const [openParentId, setOpenParentId] = useState<string | null>(null);

  const action = useAction(accounts.reload);
  const [form, setForm] = useState({
    role: "teacher" as Role,
    full_name: "",
    email: "",
    phone: "",
  });

  if (!api) return <Spinner />;

  return (
    <>
      {secret ? (
        <OneTimeSecret value={secret.temporary_password} onDismiss={() => setSecret(null)}>
          Temporary password for {secret.user.full_name}
        </OneTimeSecret>
      ) : null}

      <Panel
        title="Accounts"
        description="Nobody can register themselves. Every account starts here."
        actions={
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
        }
      >
        {accounts.loading ? <Spinner /> : null}
        {accounts.error ? <Notice>{accounts.error}</Notice> : null}

        <Table head={["Name", "Role", "Signs in with", "Last signed in", ""]} empty="No accounts.">
          {(accounts.data ?? []).map((account) => (
            <Row key={account.id}>
              <Cell>
                {account.full_name}
                {account.must_change_password ? (
                  <Badge tone="warn">Password not changed</Badge>
                ) : null}
                {account.is_active ? null : <Badge tone="bad">Deactivated</Badge>}
              </Cell>
              <Cell>{ROLE_LABELS[account.role] ?? account.role}</Cell>
              <Cell>{account.email ?? account.phone ?? "—"}</Cell>
              <Cell>{formatDateTime(account.last_login_at)}</Cell>
              <Cell className="whitespace-nowrap">
                <Button
                  variant="ghost"
                  disabled={action.busy}
                  onClick={async () => {
                    await action.run(async () => {
                      setSecret(await api.resetPassword(account.id));
                    });
                  }}
                >
                  Reset password
                </Button>
                {account.role === "parent" ? (
                  <Button
                    variant="ghost"
                    onClick={() =>
                      setOpenParentId(openParentId === account.id ? null : account.id)
                    }
                  >
                    Children
                  </Button>
                ) : null}
              </Cell>
            </Row>
          ))}
        </Table>
      </Panel>

      {openParentId ? (
        <ChildrenPanel
          key={openParentId}
          parent={(accounts.data ?? []).find((item) => item.id === openParentId)!}
        />
      ) : null}

      <Panel
        title="Create an account"
        description="An email address or a phone number — either one signs in, against the same password."
      >
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(async () => {
              setSecret(
                await api.createUser({
                  role: form.role,
                  full_name: form.full_name,
                  email: form.email || null,
                  phone: form.phone || null,
                }),
              );
            });
            if (created) setForm({ ...form, full_name: "", email: "", phone: "" });
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
          <div className="sm:col-span-2">
            <Button type="submit" disabled={action.busy}>
              Create account
            </Button>
          </div>
        </form>

        <div className="mt-3 flex flex-col gap-2">
          <Notice>{action.error}</Notice>
        </div>
      </Panel>
    </>
  );
}

function ChildrenPanel({ parent }: { parent: Account }) {
  const api = useAdminApi()!;
  const children = useResource(() => api.children(parent.id), [api, parent.id]);
  const [search, setSearch] = useState("");
  const candidates = useResource(
    () => api.pupils({ search: search || undefined, limit: 10 }),
    [api, search],
  );
  const action = useAction(children.reload);

  return (
    <Panel
      title={`${parent.full_name}'s children`}
      description="This is exactly what they will see when they sign in — nothing else."
    >
      {children.loading ? <Spinner /> : null}
      {children.error ? <Notice>{children.error}</Notice> : null}

      <ul className="flex flex-wrap gap-2">
        {(children.data ?? []).map((child) => (
          <li key={child.id}>
            <Badge tone="good">
              {pupilName(child)} ({child.admission_number})
            </Badge>
          </li>
        ))}
        {children.data?.length ? null : (
          <p className="text-sm text-[var(--muted)]">
            Nothing attached yet — this account would sign in and see an empty page.
          </p>
        )}
      </ul>

      <div className="mt-4 flex flex-col gap-3">
        <Field label="Find a pupil" hint="Search by name or admission number.">
          <Input value={search} onChange={(event) => setSearch(event.target.value)} />
        </Field>

        <Table head={["Pupil", "Admission no.", ""]} empty="Start typing to find a pupil.">
          {(candidates.data?.items ?? []).map((pupil) => (
            <Row key={pupil.id}>
              <Cell>{pupilName(pupil)}</Cell>
              <Cell>{pupil.admission_number}</Cell>
              <Cell>
                <Button
                  variant="ghost"
                  disabled={action.busy}
                  onClick={() =>
                    void action.run(
                      () =>
                        api.linkChildren(parent.id, {
                          children: [{ pupil_id: pupil.id, is_primary: false }],
                        }),
                      `${pupilName(pupil)} attached.`,
                    )
                  }
                >
                  Attach
                </Button>
              </Cell>
            </Row>
          ))}
        </Table>

        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}
