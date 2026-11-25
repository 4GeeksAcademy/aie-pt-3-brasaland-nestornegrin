import { ROLE_NAMES, STATUS_LABELS, canSend, citationLabel, waitingOn } from "../lib/supplier-contracts";

describe("helpers de proveedores y contratos", () => {
  test("la comunicación solo se puede enviar cuando está aprobada por todos", () => {
    expect(canSend({ status: "approved" })).toBe(true);
    for (const status of ["pending_approval", "rejected", "sent"] as const) expect(canSend({ status })).toBe(false);
  });
  test("indica quién falta por aprobar, con nombre de la empresa", () => {
    expect(waitingOn({ status: "pending_approval", missing_roles: ["ops_director", "ceo"] })).toBe(`${ROLE_NAMES.ops_director} y ${ROLE_NAMES.ceo}`);
    expect(waitingOn({ status: "pending_approval", missing_roles: ["ceo"] })).toBe(ROLE_NAMES.ceo);
    expect(waitingOn({ status: "approved", missing_roles: [] })).toBe("");
  });
  test("toda cita lleva contrato, cláusula y página, y marca lo dudoso", () => {
    expect(citationLabel({ contract_id: "CT-BR-02", clause: "4", page: 2, doubtful: false })).toBe("CT-BR-02, cláusula 4, p. 2");
    expect(citationLabel({ contract_id: "CT-BR-01", clause: "3", page: 2, doubtful: true })).toMatch(/dudosa/);
  });
  test("las etiquetas de estado cubren todos los estados", () => {
    expect(Object.keys(STATUS_LABELS).sort()).toEqual(["approved", "pending_approval", "rejected", "sent"]);
  });
});
