import { useMemo } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import type { AccountRow } from "../api/client";
import type { SelectionState } from "../hooks/useSelection";

interface Props {
  rows: AccountRow[];
  selection: SelectionState;
}

const columnHelper = createColumnHelper<AccountRow>();

export function AccountsTable({ rows, selection }: Props) {
  const { isSelected, toggleRow } = selection;

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "select",
        header: "",
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={isSelected(row.original.account_id)}
            onChange={() => toggleRow(row.original.account_id)}
          />
        ),
      }),
      columnHelper.accessor("account_id", { header: "Account ID" }),
      columnHelper.accessor("account_name", { header: "Name" }),
      columnHelper.accessor("industry", { header: "Industry" }),
      columnHelper.accessor("vertical", { header: "Vertical" }),
      columnHelper.accessor("segment", {
        header: "Segment",
        cell: (info) => {
          const value = info.getValue();
          if (!value) return "—";
          return <span className={`segment-badge segment-${value.toLowerCase()}`}>{value}</span>;
        },
      }),
      columnHelper.accessor("excluded", {
        header: "Excluded",
        cell: (info) => (info.getValue() ? "Yes" : "No"),
      }),
      columnHelper.accessor("state", { header: "State" }),
      columnHelper.accessor("website", { header: "Website" }),
    ],
    [isSelected, toggleRow],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (rows.length === 0) {
    return <p className="empty-state">No accounts match the current filters.</p>;
  }

  return (
    <table className="accounts-table">
      <thead>
        {table.getHeaderGroups().map((headerGroup) => (
          <tr key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <th key={header.id}>
                {flexRender(header.column.columnDef.header, header.getContext())}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id} className={isSelected(row.original.account_id) ? "row-selected" : ""}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
