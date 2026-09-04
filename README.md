# RideNG

RideNG is an Abuja-first ride-hailing platform designed for the Nigerian market.

The platform combines traditional instant ride booking with a flexible fare negotiation system, allowing riders to either accept an estimated fare or propose a price that nearby drivers can accept or counter.

## Pilot Market

RideNG will initially operate in Abuja, Federal Capital Territory, Nigeria.

The platform is being designed with multi-city architecture so that it can later expand to markets such as Lagos, Port Harcourt, Kano, and other Nigerian cities without rebuilding the core system.

## Core Product

RideNG consists of four primary systems:

1. Rider Mobile Application
2. Driver Mobile Application
3. Backend API
4. Administrative and Operations Dashboard

## Planned MVP Features

### Rider

- Phone number authentication
- GPS pickup location
- Destination search
- Fare estimation
- Instant ride booking
- Fare negotiation
- Driver selection
- Live driver tracking
- Trip PIN verification
- Cash and electronic payments
- Trip sharing
- Emergency/SOS functionality
- Driver ratings

### Driver

- Driver registration
- Identity verification
- Vehicle registration
- Document verification
- Online/offline availability
- Nearby ride requests
- Ride acceptance
- Counteroffers
- Navigation
- Trip management
- Earnings dashboard
- Driver commission wallet
- Rider ratings

### Administration

- Driver approval
- Rider management
- Driver management
- Live trip monitoring
- Trip history
- Fare configuration
- Payments
- Driver commissions
- Complaints
- Safety incidents
- Account suspension
- Analytics

## Planned Technology Stack

### Mobile
Flutter

### Backend
Python  
FastAPI

### Database
PostgreSQL  
PostGIS

### Real-Time Communication
Redis  
WebSockets

### Cloud Infrastructure
AWS

### Maps and Location
Google Maps Platform

### Payments
Paystack / Flutterwave

## Repository Structure

```text
rideng/
├── backend/
├── rider_app/
├── driver_app/
├── admin/
├── infrastructure/
├── docs/
├── README.md
└── .gitignore