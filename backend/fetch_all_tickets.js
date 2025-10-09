/**
 * fetch_all_tickets_fixed.js
 *
 * Fetch all tickets from SuperOps GraphQL API (getTicketList) using page-based pagination,
 * print each ticket JSON to the terminal.
 *
 * Requirements: Node 18+ (global fetch available).
 *
 * Environment variables:
 *   SUPEROPS_TOKEN        - (required) API token (Bearer)
 *   CUSTOMER_SUBDOMAIN    - (required) your company subdomain from Settings -> Company information
 *   PLATFORM              - (optional) "msp" (default) or "it"
 *   REGION                - (optional) "us" (default) or "eu"
 *   PAGE_SIZE             - (optional) page size (default 100)
 *   FETCH_NOTES           - (optional) "true" to fetch notes for each ticket (default false)
 *
 * Example:
 *   export SUPEROPS_TOKEN="token_here"
 *   export CUSTOMER_SUBDOMAIN="mycompany"   # required
 *   node fetch_all_tickets_fixed.js
 */

const TOKEN = "api-eyJhbGciOiJSUzI1NiJ9.eyJqdGkiOiI4MzM1MjE1MzMyNzQ2NDQ0OCIsInJhbmRvbWl6ZXIiOiJk77-977-977-977-977-977-9Ie-_vSwifQ.YTrKXb8wD4qyi5EwRrP0lU5uABkFHOZSH0HoCmtub5ajcigBNrUmw3n3GvcXl9D2TE-_0OiSxluv25WMHKUl2nxsfMCbZzb2hpUFBcbsFCAf6CJAC4v_q3qWthyLeXBVwKtqg7Mssq_qA2Wc86nyZmrE_jxgJr4EunO5Fd7GwO7u3Q4Hy_WayianxpzgzXmLJVfSnRxKMTGDrpZNobTtjR_oBYgfkRvXuA6gp5U7mbkPyW5A3LYVC1LOScITB_YnV-E8RHIfcoOLOZkKPv6MULelOxiuRlU96wEx0bsON5df8oKD22H5a7Nl2QCHFbz99cEBtOeYfRidNJW5x-h8pg";
const CUSTOMER_SUBDOMAIN = "vishwakarmainstituteoftechnology";
if (!TOKEN) {
    console.error("ERROR: set SUPEROPS_TOKEN environment variable with your SuperOps API token.");
    process.exit(1);
}
if (!CUSTOMER_SUBDOMAIN) {
    console.error("ERROR: set CUSTOMER_SUBDOMAIN environment variable with your company subdomain.");
    process.exit(1);
}

const PLATFORM = (process.env.PLATFORM || "msp").toLowerCase(); // msp or it
const REGION = (process.env.REGION || "us").toLowerCase(); // us or eu
const PAGE_SIZE = Number(process.env.PAGE_SIZE || "100");
const FETCH_NOTES = (process.env.FETCH_NOTES || "false").toLowerCase() === "true";

function buildEndpoint(platform = "msp", region = "us") {
    const host = region === "eu" ? "euapi.superops.ai" : "api.superops.ai";
    return `https://${host}/${platform}`;
}

const GRAPHQL_ENDPOINT = buildEndpoint(PLATFORM, REGION);
const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${TOKEN}`,
    "CustomerSubDomain": CUSTOMER_SUBDOMAIN,
};

async function graphqlRequest(query, variables = {}) {
    const MAX_RETRIES = 3;
    let attempt = 0;
    while (true) {
        attempt++;
        try {
            const resp = await fetch(GRAPHQL_ENDPOINT, {
                method: "POST",
                headers,
                body: JSON.stringify({ query, variables }),
            });

            const text = await resp.text();
            // try to parse JSON so we can surface GraphQL errors
            let json = null;
            try { json = text ? JSON.parse(text) : null; } catch (e) { /* ignore parse error */ }

            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status} ${resp.statusText} | body: ${text || "<empty>"}`);
            }

            if (json && json.errors && json.errors.length) {
                // Surface the GraphQL errors fully so you can debug field names / schema
                throw new Error(`GraphQL errors: ${JSON.stringify(json.errors)}`);
            }

            return json?.data ?? null;
        } catch (err) {
            if (attempt >= MAX_RETRIES) throw err;
            const delay = 500 * Math.pow(2, attempt - 1);
            console.warn(`Request error (attempt ${attempt}): ${err.message}. Retrying in ${delay}ms...`);
            await new Promise(r => setTimeout(r, delay));
        }
    }
}

/**
 * Corrected getTicketList query:
 * - removed description, department, tags (these are not valid on getTicketList per your error)
 * - requester is requested as a leaf (no {..} selection) because list endpoint exposes it as JSON/leaf
 *
 * You can extend this list with other fields shown in your developer docs, but if you get
 * GraphQL validation errors, remove the problematic fields or fetch the full ticket with getTicket.
 */
const GET_TICKET_LIST_QUERY = `
query getTicketList($input: ListInfoInput!) {
  getTicketList(input: $input) {
    tickets {
      ticketId
      displayId
      subject
      ticketType
      requestType
      source
      client
      site
      requester            # NOTE: leaf/JSON — do NOT ask for subfields here on the list endpoint
      additionalRequester
      followers
      techGroup
      technician
      status
      priority
      impact
      urgency
      category
      subcategory
      cause
      subcause
      resolutionCode
      sla
      createdTime
      updatedTime
      firstResponseDueTime
      firstResponseTime
      resolutionDueTime
      resolutionTime
      resolutionViolated
      customFields
      worklogTimespent
    }
    listInfo {
      page
      pageSize
      totalCount
    }
  }
}
`;

// optional: fetch full ticket by id (useful if you need nested requester/technician objects)
const GET_TICKET_FULL_QUERY = `
query getTicket($input: TicketIdentifierInput!) {
  getTicket(input: $input) {
    ticketId
    displayId
    subject
    ticketType
    requestType
    source
    client { accountId name }     # allowed in getTicket (full ticket) per docs
    site { id name }
    requester { userId name email }   # allowed here (full ticket)
    additionalRequester
    followers
    techGroup { groupId name }
    technician { userId name }
    status
    priority
    impact
    urgency
    category
    subcategory
    cause
    subcause
    resolutionCode
    sla { id name }
    createdTime
    updatedTime
    firstResponseDueTime
    firstResponseTime
    resolutionDueTime
    resolutionTime
    customFields
    worklogTimespent
  }
}
`;

async function fetchNotesForTicket(ticketId) {
    const GET_TICKET_NOTES_QUERY = `
  query getTicketNoteList($input: TicketIdentifierInput!) {
    getTicketNoteList(input: $input) {
      noteId
      addedBy
      addedOn
      content
      privacyType
      attachments {
        fileName
        originalFileName
        fileSize
      }
    }
  }`;
    try {
        const data = await graphqlRequest(GET_TICKET_NOTES_QUERY, { input: { ticketId } });
        return data?.getTicketNoteList ?? [];
    } catch (err) {
        console.warn(`Warning: failed to fetch notes for ${ticketId}: ${err.message}`);
        return [];
    }
}

async function fetchAllTickets({ pageSize = PAGE_SIZE, fetchNotes = FETCH_NOTES } = {}) {
    let page = 1;
    let fetched = 0;
    const all = [];

    while (true) {
        const variables = { input: { page, pageSize } };
        const data = await graphqlRequest(GET_TICKET_LIST_QUERY, variables);
        const pageObj = data?.getTicketList;
        if (!pageObj) {
            console.warn("No getTicketList data returned for page", page);
            break;
        }

        const tickets = pageObj.tickets || [];
        const listInfo = pageObj.listInfo || {};
        const totalCount = listInfo.totalCount ?? null;

        if (!tickets.length) break;

        // if the list data returns 'requester' as raw JSON (string/object), you will get it here.
        // Optionally fetch the full ticket per id to get nested requester/technician objects
        for (const t of tickets) {
            if (fetchNotes) {
                t.notes = await fetchNotesForTicket(t.ticketId);
            }
            // If you need nested objects (requester.userId etc), call getTicket for that ticket:
            // const full = await graphqlRequest(GET_TICKET_FULL_QUERY, { input: { ticketId: t.ticketId } });
            // if (full?.getTicket) t.full = full.getTicket;

            console.log(JSON.stringify(t, null, 2));
            all.push(t);
        }

        fetched += tickets.length;
        if (totalCount != null && fetched >= totalCount) break;
        page += 1;
    }

    console.log(`\nFetched ${all.length} tickets${fetchNotes ? " (with notes)" : ""}.`);
    return all;
}

(async () => {
    try {
        console.log("SuperOps GraphQL endpoint:", GRAPHQL_ENDPOINT);
        console.log("CUSTOMER_SUBDOMAIN:", CUSTOMER_SUBDOMAIN);
        console.log("PAGE_SIZE:", PAGE_SIZE, "FETCH_NOTES:", FETCH_NOTES);
        await fetchAllTickets({ pageSize: PAGE_SIZE, fetchNotes: FETCH_NOTES });
        console.log("Done.");
    } catch (err) {
        console.error("Fatal error:", err.message || err);
        process.exit(1);
    }
})();
