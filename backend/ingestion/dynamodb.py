import boto3  # type: ignore
from datetime import datetime

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
table = dynamodb.Table("FixellaTickets")

tickets = [
    {
        "ticketId": "1001",
        "displayId": "1",
        "subject": "Employee offboarding",
        "ticketType": "INCIDENT",
        "requestType": "Incident",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Dwight Schrute"},
        "technician": {
            "userId": "7076251b-17da-4881-9cfb-98c35af12df0",
            "name": "Sneha Jain",
        },
        "technician_userId": "7076251b-17da-4881-9cfb-98c35af12df0",
        "status": "Open",
        "priority": "High",
        "impact": "Medium",
        "urgency": "High",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
    {
        "ticketId": "1002",
        "displayId": "2",
        "subject": "Unable to login to email",
        "ticketType": "INCIDENT",
        "requestType": "Incident",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Dwight Schrute"},
        "technician": {
            "userId": "39f16300-9e74-4dc0-b129-1d610998a491",
            "name": "Siddhartha Chakrabarty",
        },
        "technician_userId": "39f16300-9e74-4dc0-b129-1d610998a491",
        "status": "Open",
        "priority": "Critical",
        "impact": "High",
        "urgency": "Medium",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
    {
        "ticketId": "1003",
        "displayId": "3",
        "subject": "Mouse issues",
        "ticketType": "INCIDENT",
        "requestType": "Incident",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Dwight Schrute"},
        "technician": {
            "userId": "7076251b-17da-4881-9cfb-98c35af12df0",
            "name": "Sneha Jain",
        },
        "technician_userId": "7076251b-17da-4881-9cfb-98c35af12df0",
        "status": "Open",
        "priority": "Medium",
        "impact": "Medium",
        "urgency": "Medium",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
    # More tickets
    {
        "ticketId": "1004",
        "displayId": "4",
        "subject": "Printer not responding",
        "ticketType": "INCIDENT",
        "requestType": "Incident",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Jim Halpert"},
        "technician": {
            "userId": "39f16300-9e74-4dc0-b129-1d610998a491",
            "name": "Siddhartha Chakrabarty",
        },
        "technician_userId": "39f16300-9e74-4dc0-b129-1d610998a491",
        "status": "Open",
        "priority": "High",
        "impact": "Medium",
        "urgency": "High",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
    {
        "ticketId": "1005",
        "displayId": "5",
        "subject": "VPN connection failure",
        "ticketType": "INCIDENT",
        "requestType": "Incident",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Pam Beesly"},
        "technician": {
            "userId": "7076251b-17da-4881-9cfb-98c35af12df0",
            "name": "Sneha Jain",
        },
        "technician_userId": "7076251b-17da-4881-9cfb-98c35af12df0",
        "status": "Open",
        "priority": "Critical",
        "impact": "High",
        "urgency": "High",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
    {
        "ticketId": "1006",
        "displayId": "6",
        "subject": "Software installation request",
        "ticketType": "REQUEST",
        "requestType": "Request",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Stanley Hudson"},
        "technician": {
            "userId": "39f16300-9e74-4dc0-b129-1d610998a491",
            "name": "Siddhartha Chakrabarty",
        },
        "technician_userId": "39f16300-9e74-4dc0-b129-1d610998a491",
        "status": "Open",
        "priority": "Medium",
        "impact": "Medium",
        "urgency": "Medium",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
    {
        "ticketId": "1007",
        "displayId": "7",
        "subject": "Email sync issue",
        "ticketType": "INCIDENT",
        "requestType": "Incident",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Kevin Malone"},
        "technician": {
            "userId": "39f16300-9e74-4dc0-b129-1d610998a491",
            "name": "Siddhartha Chakrabarty",
        },
        "technician_userId": "39f16300-9e74-4dc0-b129-1d610998a491",
        "status": "Open",
        "priority": "High",
        "impact": "Medium",
        "urgency": "High",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
    {
        "ticketId": "1008",
        "displayId": "8",
        "subject": "Laptop overheating",
        "ticketType": "INCIDENT",
        "requestType": "Incident",
        "source": "FORM",
        "client": {"accountId": "6028532731226112000", "name": "Dunder Mifflin"},
        "site": {"id": "6028532731314192384", "name": "Scranton HQ"},
        "requester": {"userId": "6049390062889756912", "name": "Angela Martin"},
        "technician": {
            "userId": "7076251b-17da-4881-9cfb-98c35af12df0",
            "name": "Sneha Jain",
        },
        "technician_userId": "7076251b-17da-4881-9cfb-98c35af12df0",
        "status": "Open",
        "priority": "High",
        "impact": "High",
        "urgency": "High",
        "createdTime": datetime.utcnow().isoformat(),
        "updatedTime": datetime.utcnow().isoformat(),
        "worklogTimespent": "0.00",
    },
]

for ticket in tickets:
    table.put_item(Item=ticket)
    print(f"Inserted ticket {ticket['ticketId']}")












