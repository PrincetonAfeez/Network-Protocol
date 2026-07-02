# ToyProto Schema

This folder contains simple schema reference files for the ToyProto network protocol.
They document the frame header, message bodies, application commands, error codes,
and state-machine rules in a machine-readable JSON format.

These files are documentation/reference artifacts only. They do not change runtime
behavior and can be copied into the root of the `Network-Protocol` repository.

## Files

- `frame.schema.json` — 52-byte ToyProto frame header and authentication layout.
- `messages.schema.json` — protocol message opcodes and body fields.
- `app.schema.json` — application command request/response schemas.
- `errors.schema.json` — protocol error codes and severity.
- `state_machine.schema.json` — allowed endpoint states and transitions.

## Placement

Copy the full `Schema/` folder into the repository root:

```text
Network-Protocol/
  Schema/
    README.md
    frame.schema.json
    messages.schema.json
    app.schema.json
    errors.schema.json
    state_machine.schema.json
```
