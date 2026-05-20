# Notion Tracker Structure

Parent page: "🏆 World Cup 2026 Analytics Project"
Page ID: 35b8c1b5-f7c8-8195-8a6d-c954ab0deaad

## Databases

### Session Log
- ID: 39ebb2b0-f18e-4fc3-8d3d-d9872796738f
- Data source: collection://fb0605f6-6320-4d1d-ab8b-9d3c9162e0e3
- Schema: Session (title), Date, Duration (min), What I did,
  What I learned, Blockers / Open Questions, Next session pickup

### Versions
- ID: aa71891d-3ba3-47b0-b8d8-d027b49a29e3
- Data source: collection://d6d4478f-515f-431e-9a39-f1f6d871780d
- Schema: Version (title), Description, Status
  {Planning, In Progress, Shipped, Postponed}, Start Date,
  Target Date, Shipped Date, Git Tag, Limitations,
  Tasks (relation → Tasks)

### Tasks
- ID: e27118174ebe4b30bab7f62631abedd3
- Data source: collection://25b396cb-8d79-44a8-a13d-1d67f6cf8719
- Schema: Task (title), Type {Setup, Data, Code, Docs, Decision,
  Research}, Status {Backlog, In Progress, Blocked, Done},
  Estimate {Quick, Small, Medium, Big}, Start Date, Due Date,
  Version (relation → Versions), Parent Task (self-relation),
  Subtasks (self-relation), Notes, GitHub Link

## Update pattern at session end
1. Always FETCH first before UPDATE to get current state.
2. Show me the draft of what you're about to write.
3. After my confirmation, write to Notion.
4. Use the Notion connector's create-pages and update-page tools.
