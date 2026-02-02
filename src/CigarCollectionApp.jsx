


import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { ukMarketPrices } from './uk_market_prices.js';
// Google Sheets Configuration
const GOOGLE_SHEETS_CONFIG = {
  clientId: '945855470299-l1is4q9t6lb1ak8v5n0871hsk6kt8ihl.apps.googleusercontent.com',
  sheetId: '10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A',
  collectionRange: 'A:T',
  onwardsRange: 'Onwards!A:M',
  onwardsSheetId: 1785734797,
  historyRange: 'History!A:F',
  historySheetId: 563552694,
  settingsRange: 'Settings!B2',
  settingsSheetId: 1098381136,
  scopes: 'https://www.googleapis.com/auth/spreadsheets',
};

// Supported currencies
const CURRENCIES = ['USD', 'GBP', 'EUR', 'CHF', 'JPY', 'CAD', 'AUD', 'CNY', 'HKD', 'SGD'];
const CURRENCY_SYMBOLS = {
  USD: '$', GBP: '£', EUR: '€', CHF: 'CHF ', JPY: '¥', 
  CAD: 'C$', AUD: 'A$', CNY: '¥', HKD: 'HK$', SGD: 'S$'
};

// Convert amount from one currency to another using FX rates
const convertCurrency = (amount, fromCurrency, toCurrency, rates) => {
  if (!rates || !amount || fromCurrency === toCurrency) return amount;
  
  // Rates are relative to base currency
  const fromRate = rates[fromCurrency] || 1;
  const toRate = rates[toCurrency] || 1;
  
  return (amount / fromRate) * toRate;
};

// Google Auth State (will be set by OAuth)
let googleAccessToken = null;

// Parse date from various formats
const parseDate = (dateStr) => {
  if (!dateStr) return '';
  
  // Trim whitespace
  const str = String(dateStr).trim();
  if (!str) return '';
  
  const monthNamesFull = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
  const monthNamesShort = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  
  // Try parsing "Month Year" format with full year (e.g., "May 2025", "January 2025", "Nov 2023")
  const monthYearFullMatch = str.match(/^([A-Za-z]+)\s+(\d{4})$/);
  if (monthYearFullMatch) {
    const monthIndex = monthNamesFull.indexOf(monthYearFullMatch[1].toLowerCase());
    const shortIndex = monthNamesShort.indexOf(monthYearFullMatch[1].toLowerCase());
    const finalIndex = monthIndex !== -1 ? monthIndex : shortIndex;
    if (finalIndex !== -1) {
      return `${monthYearFullMatch[2]}-${String(finalIndex + 1).padStart(2, '0')}`;
    }
  }
  
  // Try parsing "Month Year" format with short year (e.g., "Jan 25", "May 24")
  const monthYearShortMatch = str.match(/^([A-Za-z]+)\s+(\d{2})$/);
  if (monthYearShortMatch) {
    const monthIndex = monthNamesFull.indexOf(monthYearShortMatch[1].toLowerCase());
    const shortIndex = monthNamesShort.indexOf(monthYearShortMatch[1].toLowerCase());
    const finalIndex = monthIndex !== -1 ? monthIndex : shortIndex;
    if (finalIndex !== -1) {
      const year = parseInt(monthYearShortMatch[2]) + 2000;
      return `${year}-${String(finalIndex + 1).padStart(2, '0')}`;
    }
  }
  
  // Try parsing "Day Month Year" format (e.g., "17 Jul 2025", "1 January 2024")
  const dayMonthYearMatch = str.match(/^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/);
  if (dayMonthYearMatch) {
    const monthIndex = monthNamesFull.indexOf(dayMonthYearMatch[2].toLowerCase());
    const shortIndex = monthNamesShort.indexOf(dayMonthYearMatch[2].toLowerCase());
    const finalIndex = monthIndex !== -1 ? monthIndex : shortIndex;
    if (finalIndex !== -1) {
      return `${dayMonthYearMatch[3]}-${String(finalIndex + 1).padStart(2, '0')}-${String(dayMonthYearMatch[1]).padStart(2, '0')}`;
    }
  }
  
  // Try YYYY-MM format (already correct)
  const monthMatch = str.match(/^(\d{4})-(\d{2})$/);
  if (monthMatch) {
    return str;
  }
  
  // Try YYYY-MM-DD format (already correct)
  const isoMatch = str.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoMatch) {
    return str;
  }
  
  return '';
};

// Format date for Google Sheets (e.g., "Jan 2025" for month-only, "17 Jul 2025" for full date)
const formatDateForSheet = (dateStr) => {
  if (!dateStr) return '';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  
  // Handle YYYY-MM format (month picker)
  const monthParts = dateStr.match(/^(\d{4})-(\d{2})$/);
  if (monthParts) {
    const year = monthParts[1];
    const month = parseInt(monthParts[2]) - 1;
    return `${months[month]} ${year}`;
  }
  
  // Handle YYYY-MM-DD format
  const dateParts = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateParts) {
    const year = dateParts[1];
    const month = parseInt(dateParts[2]) - 1;
    const day = parseInt(dateParts[3]);
    return `${day} ${months[month]} ${year}`;
  }
  
  // Fallback for other formats
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '';
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
};

// Parse currency string to number
const parseCurrency = (str) => {
  if (!str) return 0;
  return parseFloat(str.replace(/[^0-9.-]/g, '')) || 0;
};

// Format currency for Google Sheets
const formatCurrencyForSheet = (num) => {
  if (!num) return '';
  return `US$${num.toFixed(2)}`;
};

// Fetch data from Google Sheets (requires OAuth token)
const fetchSheetData = async (accessToken) => {
  const { sheetId, collectionRange } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${collectionRange}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!response.ok) throw new Error('Failed to fetch sheet data');
    const data = await response.json();
    return data.values || [];
  } catch (error) {
    console.error('Error fetching sheet data:', error);
    return null;
  }
};

// Fetch onwards data from Google Sheets (requires OAuth token)
const fetchOnwardsData = async (accessToken) => {
  const { sheetId, onwardsRange } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${onwardsRange}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!response.ok) throw new Error('Failed to fetch onwards data');
    const data = await response.json();
    return data.values || [];
  } catch (error) {
    console.error('Error fetching onwards data:', error);
    return null;
  }
};

// Transform sheet row to box object
const rowToBox = (row, index) => {
  // Columns: Date of Purchase | Box Number | Received | Brand | Name | Quantity Purchased | Number / Box | Currency | Price / Box | Price / Cigar | Ageing / Immediate | Date of Box | Code | Location | Number Consumed | Number Remaining | Ring Gauge | Length | Vitola | Notes
  return {
    id: index + 1,
    datePurchased: parseDate(row[0]),
    boxNum: row[1] || '',
    received: row[2] === 'TRUE',
    brand: row[3] || '',
    name: row[4] || '',
    qty: parseInt(row[5]) || 1,
    perBox: parseInt(row[6]) || 0,
    currency: row[7] || 'USD',
    price: parseCurrency(row[8]),
    pricePerCigar: parseCurrency(row[9]),
    status: row[10] || 'Ageing',
    dateOfBox: parseDate(row[11]),
    code: row[12] || '',
    location: row[13] || 'Cayman',
    consumed: parseInt(row[14]) || 0,
    remaining: parseInt(row[15]) || 0,
    ringGauge: row[16] || '',
    length: row[17] || '',
    vitola: row[18] || '',
    boxNotes: row[19] || '',
  };
};

// Transform onwards row to onwards object
const rowToOnwards = (row, index) => {
  // Columns: Date of Purchase | Received | Brand | Name | Qty | Per Box | Price/Box | Price/Cigar | Sale Date | Sale Price | Sale Price Base | Profit | Sold To
  // Index:   0                | 1        | 2     | 3    | 4   | 5       | 6         | 7           | 8         | 9          | 10              | 11     | 12
  const costUSD = parseCurrency(row[6]);
  const saleDate = parseDate(row[8]);
  const salePriceOriginal = parseCurrency(row[9]);
  const salePriceBase = parseCurrency(row[10]);
  const profit = parseCurrency(row[11]);
  
  // Use the USD base price if available, otherwise fall back to original
  const salePrice = salePriceBase || salePriceOriginal;
  
  return {
    id: index + 100,
    datePurchased: parseDate(row[0]),
    received: row[1] === 'TRUE',
    brand: row[2] || '',
    name: row[3] || '',
    qty: parseInt(row[4]) || 1,
    perBox: parseInt(row[5]) || 0,
    costUSD: costUSD,
    saleDate: saleDate,
    salePriceUSD: salePrice || null,
    profitUSD: profit || 0,
    soldTo: row[12] || '',
    type: salePrice > 0 ? (profit > 0 ? 'sold' : profit < 0 ? 'sold-at-loss' : 'sold-at-cost') : 'pending',
  };
};

// Transform box object to sheet row
const boxToRow = (box) => {
  // Columns: Date of Purchase | Box Number | Received | Brand | Name | Quantity Purchased | Number / Box | Currency | Price / Box | Price / Cigar | Ageing / Immediate | Date of Box | Code | Location | Number Consumed | Number Remaining | Ring Gauge | Length | Vitola | Notes
  const pricePerCigar = box.perBox > 0 ? box.price / box.perBox : 0;
  return [
    formatDateForSheet(box.datePurchased),
    box.boxNum,
    box.received ? 'TRUE' : 'FALSE',
    box.brand,
    box.name,
    box.qty || 1,
    box.perBox,
    box.currency || 'USD',
    box.price,
    pricePerCigar,
    box.status,
    box.dateOfBox ? formatDateForSheet(box.dateOfBox) : '',
    box.code || '',
    box.location,
    box.consumed,
    box.remaining,
    box.ringGauge || '',
    box.length || '',
    box.vitola || '',
    box.boxNotes || '',
  ];
};

// Update a single cell in Google Sheets (requires OAuth token)
const updateSheetCell = async (range, value, accessToken) => {
  const { sheetId } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${range}?valueInputOption=USER_ENTERED`;
  
  try {
    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        range: range,
        values: [[value]],
      }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error?.message || 'Failed to update cell');
    }
    return true;
  } catch (error) {
    console.error('Error updating cell:', error);
    return false;
  }
};

// Update a row in Google Sheets (requires OAuth token)
const updateSheetRow = async (rowIndex, values, accessToken) => {
  const { sheetId } = GOOGLE_SHEETS_CONFIG;
  const range = `A${rowIndex}:O${rowIndex}`;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${range}?valueInputOption=USER_ENTERED`;
  
  try {
    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        range: range,
        values: [values],
      }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error?.message || 'Failed to update row');
    }
    return true;
  } catch (error) {
    console.error('Error updating row:', error);
    return false;
  }
};

// Append a new row to Google Sheets (requires OAuth token)
const appendSheetRow = async (values, accessToken) => {
  const { sheetId } = GOOGLE_SHEETS_CONFIG;
  
  // First, find the "Subtotal Spent" row
  const findUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/'Cigar Inventory'!A:A`;
  
  try {
    const findResponse = await fetch(findUrl, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    const findData = await findResponse.json();
    const rows = findData.values || [];
    
    // Find the row index where "Subtotal Spent" is located
    let insertRowIndex = rows.length + 1; // Default to end
    for (let i = 0; i < rows.length; i++) {
      if (rows[i][0] && rows[i][0].includes('Subtotal')) {
        insertRowIndex = i + 1; // Convert to 1-based index
        break;
      }
    }
    
    // Insert a blank row at that position
    const insertUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}:batchUpdate`;
    const insertResponse = await fetch(insertUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        requests: [{
          insertDimension: {
            range: {
              sheetId: 1253000469,
              dimension: 'ROWS',
              startIndex: insertRowIndex - 1,
              endIndex: insertRowIndex
            },
            inheritFromBefore: insertRowIndex > 1
          }
        }]
      }),
    });
    
    if (!insertResponse.ok) {
      const error = await insertResponse.json();
      throw new Error(error.error?.message || 'Failed to insert row');
    }
    
    // Now write the data to that row
    const writeUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/'Cigar Inventory'!A${insertRowIndex}:T${insertRowIndex}?valueInputOption=USER_ENTERED`;
    const writeResponse = await fetch(writeUrl, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        range: `'Cigar Inventory'!A${insertRowIndex}:T${insertRowIndex}`,
        values: [values],
      }),
    });
    
    if (!writeResponse.ok) {
      const error = await writeResponse.json();
      throw new Error(error.error?.message || 'Failed to write row');
    }
    
    return true;
  } catch (error) {
    console.error('Error appending row:', error);
    return false;
  }
};

// Delete a row from Google Sheets by finding the box number first
const deleteSheetRow = async (boxNum, accessToken) => {
  const { sheetId, collectionRange } = GOOGLE_SHEETS_CONFIG;
  
  try {
    // First, fetch all data to find the row with matching box number
    const fetchUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${collectionRange}`;
    const fetchResponse = await fetch(fetchUrl, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!fetchResponse.ok) throw new Error('Failed to fetch sheet data');
    const data = await fetchResponse.json();
    const rows = data.values || [];
    
    // Find the row index (box number is in column B, index 1)
    // Handle both exact match and comma-separated box numbers (e.g., "2.1, 2.2")
    let rowIndex = -1;
    for (let i = 0; i < rows.length; i++) {
      const cellValue = rows[i][1] || '';
      const boxNums = cellValue.split(',').map(s => s.trim());
      if (cellValue === String(boxNum) || cellValue === boxNum || boxNums.includes(String(boxNum))) {
        rowIndex = i + 1; // +1 because sheets are 1-indexed
        break;
      }
    }
    
    if (rowIndex === -1) {
      throw new Error(`Box number ${boxNum} not found in sheet`);
    }
    
    // Now delete the row
    const deleteUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}:batchUpdate`;
    const response = await fetch(deleteUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        requests: [{
          deleteDimension: {
            range: {
              sheetId: 1253000469,
              dimension: 'ROWS',
              startIndex: rowIndex - 1,
              endIndex: rowIndex
            }
          }
        }]
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error?.message || 'Failed to delete row');
    }
    
    return true;
  } catch (error) {
    console.error('Error deleting row:', error);
    return false;
  }
};

// Update a row in Google Sheets by finding the box number first
const updateBoxInSheet = async (boxNum, updatedData, accessToken) => {
  const { sheetId, collectionRange } = GOOGLE_SHEETS_CONFIG;
  
  try {
    // First, fetch all data to find the row with matching box number
    const fetchUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${collectionRange}`;
    const fetchResponse = await fetch(fetchUrl, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!fetchResponse.ok) throw new Error('Failed to fetch sheet data');
    const data = await fetchResponse.json();
    const rows = data.values || [];
    
    // Find the row index (box number is in column B, index 1)
    let rowIndex = -1;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i][1] === String(boxNum) || rows[i][1] === boxNum) {
        rowIndex = i + 1; // +1 because sheets are 1-indexed
        break;
      }
    }
    
    if (rowIndex === -1) {
      throw new Error(`Box number ${boxNum} not found in sheet`);
    }
    
   // Build the row data in the correct order (A:T)
    const pricePerCigar = updatedData.perBox > 0 ? updatedData.price / updatedData.perBox : 0;
    const rowData = [
      updatedData.datePurchased ? formatDateForSheet(updatedData.datePurchased) : '',  // A - Date of Purchase
      updatedData.boxNum || boxNum,  // B - Box Number
      updatedData.received ? 'TRUE' : 'FALSE',  // C - Received
      updatedData.brand || '',  // D - Brand
      updatedData.name || '',  // E - Name
      updatedData.qty || 1,  // F - Quantity Purchased
      updatedData.perBox || '',  // G - Number / Box
      updatedData.currency || 'USD',  // H - Currency
      updatedData.price || '',  // I - Price / Box
      pricePerCigar,  // J - Price / Cigar
      updatedData.status || '',  // K - Ageing / Immediate
      updatedData.dateOfBox ? formatDateForSheet(updatedData.dateOfBox) : '',  // L - Date of Box
      updatedData.code || '',  // M - Code
      updatedData.location || '',  // N - Location
      updatedData.consumed || 0,  // O - Number Consumed
      updatedData.remaining || 0,  // P - Number Remaining
      updatedData.ringGauge || '',  // Q - Ring Gauge
      updatedData.length || '',  // R - Length
      updatedData.vitola || '',  // S - Vitola
      updatedData.boxNotes || '',  // T - Notes
    ];
    
    // Update the row
    const updateUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/'Cigar Inventory'!A${rowIndex}:T${rowIndex}?valueInputOption=USER_ENTERED`;
    const response = await fetch(updateUrl, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        values: [rowData]
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error?.message || 'Failed to update row');
    }
    
    return true;
  } catch (error) {
    console.error('Error updating row:', error);
    return false;
  }
};

// Fetch history data from Google Sheets (requires OAuth token)
const fetchHistoryData = async (accessToken) => {
  const { sheetId, historyRange } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${historyRange}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!response.ok) throw new Error('Failed to fetch history data');
    const data = await response.json();
    return data.values || [];
  } catch (error) {
    console.error('Error fetching history data:', error);
    return null;
  }
};

// Fetch settings from Google Sheets (requires OAuth token)
const fetchSettings = async (accessToken) => {
  const { sheetId } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/Settings!A:B`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!response.ok) throw new Error('Failed to fetch settings');
    const data = await response.json();
    const rows = data.values || [];
    
    // Convert rows to object (skip header row)
    const settings = {};
    rows.slice(1).forEach(row => {
      if (row[0]) {
        settings[row[0]] = row[1]?.toLowerCase() === 'true' ? true : row[1]?.toLowerCase() === 'false' ? false : row[1];
      }
    });
    return settings;
  } catch (error) {
    console.error('Error fetching settings:', error);
    return null;
  }
};

// Fetch FX rates from frankfurter.app
const fetchFxRates = async (base = 'USD') => {
  try {
    const currencies = CURRENCIES.filter(c => c !== base).join(',');
    const response = await fetch(`https://api.frankfurter.app/latest?from=${base}&to=${currencies}`);
    if (!response.ok) throw new Error('Failed to fetch FX rates');
    const data = await response.json();
    // Add the base currency with rate 1
    const rates = { ...data.rates, [base]: 1 };
    return { rates, date: data.date };
  } catch (error) {
    console.error('Error fetching FX rates:', error);
    return null;
  }
};

// Save a setting to Google Sheets
const saveSetting = async (settingName, value, accessToken) => {
  const { sheetId } = GOOGLE_SHEETS_CONFIG;
  
  try {
    // First, fetch all settings to find the row
    const fetchUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/Settings!A:B`;
    const fetchResponse = await fetch(fetchUrl, {
      headers: { 'Authorization': `Bearer ${accessToken}` },
    });
    const data = await fetchResponse.json();
    const rows = data.values || [];
    
    // Find the row with this setting
    let rowIndex = -1;
    for (let i = 1; i < rows.length; i++) {
      if (rows[i][0] === settingName) {
        rowIndex = i + 1; // +1 because sheets are 1-indexed
        break;
      }
    }
    
    if (rowIndex === -1) {
      // Setting doesn't exist, append it
      const appendUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/Settings!A:B:append?valueInputOption=USER_ENTERED`;
      await fetch(appendUrl, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          values: [[settingName, String(value)]]
        }),
      });
    } else {
      // Update existing setting
      const updateUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/Settings!B${rowIndex}?valueInputOption=USER_ENTERED`;
      await fetch(updateUrl, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          values: [[String(value)]]
        }),
      });
    }
    return true;
  } catch (error) {
    console.error('Error saving setting:', error);
    return false;
  }
};

// Add a smoke log entry to sheet
const addHistoryEntry = async (entry, accessToken) => {
  const { sheetId, historyRange } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${historyRange}:append?valueInputOption=USER_ENTERED`;
  
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        values: [[entry.date, entry.boxNum, entry.brand, entry.name, entry.qty, entry.notes || '']]
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error?.message || 'Failed to add history entry');
    }
    
    return true;
  } catch (error) {
    console.error('Error adding history entry:', error);
    return false;
  }
};

// Update a history entry in place
const updateHistoryEntry = async (oldEntry, newEntry, accessToken) => {
  const { sheetId, historyRange, historySheetId } = GOOGLE_SHEETS_CONFIG;
  
  try {
    // Fetch all history to find the matching row
    const fetchUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${historyRange}`;
    const fetchResponse = await fetch(fetchUrl, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!fetchResponse.ok) throw new Error('Failed to fetch history data');
    const data = await fetchResponse.json();
    const rows = data.values || [];
    
    // Helper to normalize dates for comparison
    const normalizeDate = (dateStr) => {
      if (!dateStr) return '';
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return dateStr;
      return d.toISOString().split('T')[0]; // YYYY-MM-DD
    };
    
    // Find the row (match date, boxNum, brand, name, qty)
    let rowIndex = -1;
    const oldDateNorm = normalizeDate(oldEntry.date);
    for (let i = 1; i < rows.length; i++) { // Start at 1 to skip header
      const rowDateNorm = normalizeDate(rows[i][0]);
      if (rowDateNorm === oldDateNorm && 
          String(rows[i][1]) === String(oldEntry.boxNum) && 
          rows[i][2] === oldEntry.brand && 
          rows[i][3] === oldEntry.name && 
          String(rows[i][4]) === String(oldEntry.qty)) {
        rowIndex = i + 1; // +1 because sheets are 1-indexed
        break;
      }
    }
    
    if (rowIndex === -1) {
      console.error('History entry not found for update');
      return false;
    }
    
    // Update the row in place
      const sheetName = historyRange.split('!')[0];
      const updateUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${sheetName}!A${rowIndex}:F${rowIndex}?valueInputOption=USER_ENTERED`;    const response = await fetch(updateUrl, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        values: [[newEntry.date, newEntry.boxNum, newEntry.brand, newEntry.name, newEntry.qty, newEntry.notes || '']]
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error?.message || 'Failed to update history entry');
    }
    
    return true;
  } catch (error) {
    console.error('Error updating history entry:', error);
    return false;
  }
};

// Delete a history entry by finding and removing the row
const deleteHistoryEntry = async (entry, accessToken) => {
  const { sheetId, historyRange, historySheetId } = GOOGLE_SHEETS_CONFIG;
  
  try {
    // Fetch all history to find the matching row
    const fetchUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${historyRange}`;
    const fetchResponse = await fetch(fetchUrl, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!fetchResponse.ok) throw new Error('Failed to fetch history data');
    const data = await fetchResponse.json();
    const rows = data.values || [];
    
    // Find the row (match date, boxNum, brand, name, qty)
    let rowIndex = -1;
    for (let i = 1; i < rows.length; i++) { // Start at 1 to skip header
      if (rows[i][0] === entry.date && 
          String(rows[i][1]) === String(entry.boxNum) && 
          rows[i][2] === entry.brand && 
          rows[i][3] === entry.name && 
          String(rows[i][4]) === String(entry.qty)) {
        rowIndex = i + 1; // +1 because sheets are 1-indexed
        break;
      }
    }
    
    if (rowIndex === -1) {
      throw new Error('History entry not found');
    }
    
    // Delete the row
    const deleteUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}:batchUpdate`;
    const response = await fetch(deleteUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        requests: [{
          deleteDimension: {
            range: {
              sheetId: historySheetId,
              dimension: 'ROWS',
              startIndex: rowIndex - 1,
              endIndex: rowIndex
            }
          }
        }]
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error?.message || 'Failed to delete history entry');
    }
    
    return true;
  } catch (error) {
    console.error('Error deleting history entry:', error);
    return false;
  }
};

// Fetch highest box number from Settings (requires OAuth token)
const fetchHighestBoxNum = async (accessToken) => {
  const { sheetId, settingsRange } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${settingsRange}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },
    });
    if (!response.ok) throw new Error('Failed to fetch settings');
    const data = await response.json();
    return parseInt(data.values?.[0]?.[0]) || 0;
  } catch (error) {
    console.error('Error fetching highest box num:', error);
    return 0;
  }
};

// Update highest box number in Settings
const updateHighestBoxNum = async (num, accessToken) => {
  const { sheetId, settingsRange } = GOOGLE_SHEETS_CONFIG;
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${settingsRange}?valueInputOption=USER_ENTERED`;
  
  try {
    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        values: [[num]]
      }),
    });
    
    if (!response.ok) throw new Error('Failed to update settings');
    return true;
  } catch (error) {
    console.error('Error updating highest box num:', error);
    return false;
  }
};

// Default exchange rate (fallback if API fails)
const DEFAULT_FX_RATE = 0.79;

// Convert status value to display name
const getStatusDisplay = (status) => {
  if (status === 'Immediate') return 'On Rotation';
  if (status === 'Combination') return 'Assortment';
  return status || 'Ageing';
};

// Format helpers
const fmt = {
  usd: (v) => `$${v.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0})}`,
  gbp: (v) => `£${v.toLocaleString('en-GB', {minimumFractionDigits: 0, maximumFractionDigits: 0})}`,
  date: (d) => d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '-',
  monthYear: (d) => {
    if (!d) return '-';
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    // Handle YYYY-MM format
    const monthMatch = d.match(/^(\d{4})-(\d{2})$/);
    if (monthMatch) {
      return `${months[parseInt(monthMatch[2]) - 1]} ${monthMatch[1]}`;
    }
    // Handle YYYY-MM-DD format
    const dateMatch = d.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (dateMatch) {
      return `${months[parseInt(dateMatch[2]) - 1]} ${dateMatch[1]}`;
    }
    return d;
  },
  currency: (v, curr) => {
    const symbol = CURRENCY_SYMBOLS[curr] || '$';
    const locale = curr === 'GBP' ? 'en-GB' : curr === 'EUR' ? 'de-DE' : curr === 'JPY' ? 'ja-JP' : curr === 'CNY' ? 'zh-CN' : 'en-US';
    const decimals = curr === 'JPY' ? 0 : 0;
    return `${symbol}${v.toLocaleString(locale, {minimumFractionDigits: decimals, maximumFractionDigits: decimals})}`;
  },
};

// Price metadata
const PRICE_META = {
  lastUpdated: '2025-01-20',
  sources: ['C.Gars Ltd', 'JJ Fox', 'Davidoff', 'Hunters & Frankau'],
};

// Brand logos
const brandImages = {
  'Cohiba': 'data:image/webp;base64,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',
  'Trinidad': 'data:image/png;base64,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',
  'Montecristo': 'data:image/png;base64,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',
  'Hoyo de Monterrey': 'data:image/png;base64,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',
  'Ramon Allones': 'data:image/png;base64,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',
  'Bolivar': 'data:image/png;base64,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',
  'Partagas': 'data:image/png;base64,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',
};

// Brand styling - based on authentic cigar band colors
const brandStyles = {
  'Cohiba': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Trinidad': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Montecristo': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Hoyo de Monterrey': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Ramon Allones': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Bolivar': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Partagas': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'H. Upmann': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Punch': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' }, // Wheat & black
  'Romeo y Julieta': { bg: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', text: '#1a1a1a', accent: '#1a1a1a', border: '#1a1a1a' } // Wheat & black
};

// UK Market prices (GBP) - can be updated via external JSON
const ukMarket = {
  'Cohiba': {
    'Vistosos': { gbp: 2100, perBox: 10, source: 'C.Gars' },
    'Siglo VI': { gbp: 2899, perBox: 25, source: 'C.Gars' },
    'Maduro 5 Genios': { gbp: 2750, perBox: 25, source: 'C.Gars' },
    'Maduro 5 Magicos': { gbp: 2250, perBox: 25, source: 'C.Gars' },
    'Behike 52': { gbp: 3399, perBox: 10, source: 'C.Gars' },
    'Behike 56': { gbp: 4500, perBox: 10, source: 'C.Gars' },
    'Siglo I': { gbp: 950, perBox: 25, source: 'C.Gars' },
    'Medio Siglo': { gbp: 1650, perBox: 25, source: 'C.Gars' },
    'Lanceros': { gbp: 2800, perBox: 25, source: 'C.Gars' },
  },
  'Trinidad': { 
    'Robusto Extra': { gbp: 950, perBox: 12, source: 'C.Gars' },
    'Esmerelda': { gbp: 650, perBox: 12, source: 'JJ Fox' },
  },
  'Montecristo': {
    'Brilllantes': { gbp: 1450, perBox: 18, source: 'C.Gars' },
    'Leyendas': { gbp: 1100, perBox: 20, source: 'C.Gars' },
  },
  'Hoyo de Monterrey': {
    'Destinos': { gbp: 1600, perBox: 20, source: 'JJ Fox' },
    'Double Corona': { gbp: 1950, perBox: 50, source: 'C.Gars' },
    'Petit Robustos': { gbp: 625, perBox: 25, source: 'C.Gars' },
  },
  'Ramon Allones': { 'Absolutos': { gbp: 1750, perBox: 20, source: 'C.Gars' } },
  'Bolivar': { 'New Gold Medal': { gbp: 600, perBox: 10, source: 'C.Gars' } },
  'Partagas': {
    'Lusitinas': { gbp: 450, perBox: 10, source: 'C.Gars' },
    'Linea Maestra Maestros': { gbp: 1500, perBox: 20, source: 'JJ Fox' },
  }
};

// Get UK market price with priority: manual override > scraped > hardcoded fallback
const getMarket = (brand, name, perBox) => {
  // 1. Check for manual price override first (stored in localStorage)
  const manualKey = `ukPrice_${brand}_${name}_${perBox}`;
  try {
    const manualPrice = localStorage.getItem(manualKey);
    if (manualPrice) {
      const parsed = JSON.parse(manualPrice);
      return {
        gbp: parsed.gbp,
        perCigarGBP: parsed.gbp / perBox,
        source: 'manual'
      };
    }
  } catch (e) {
    console.warn('Error reading manual price:', e);
  }
  
  // 2. Check scraped prices (uk_market_prices.js) - PRIMARY SOURCE
  if (ukMarketPrices && ukMarketPrices[brand]) {
    const scrapedBrand = ukMarketPrices[brand];
    
    // Try exact match with box size
    const exactKey = `${name} (Box of ${perBox})`;
    if (scrapedBrand[exactKey]) {
      const data = scrapedBrand[exactKey];
      return {
        gbp: data.boxPrice,
        perCigarGBP: data.perCigar,
        source: (data.sources || []).join(', ') || 'scraped'
      };
    }
    
    // Try matching just by name (any box size) and adjust
    for (const [productKey, data] of Object.entries(scrapedBrand)) {
      if (productKey.startsWith(name + ' (Box of')) {
        const ratio = perBox / data.boxSize;
        return {
          gbp: data.boxPrice * ratio,
          perCigarGBP: data.perCigar,
          source: (data.sources || []).join(', ') + ' (adj)'
        };
      }
    }
  }
  
  // 3. Fall back to hardcoded ukMarket (FALLBACK)
  const m = ukMarket[brand]?.[name];
  if (m) {
    const ratio = perBox / m.perBox;
    return {
      gbp: m.gbp * ratio,
      perCigarGBP: m.gbp / m.perBox,
      source: m.source + ' (fallback)'
    };
  }
  
  return null;
};

// Helper functions for manual price overrides
const setManualUKPrice = (brand, name, perBox, gbpPrice) => {
  const key = `ukPrice_${brand}_${name}_${perBox}`;
  if (gbpPrice === null || gbpPrice === '' || isNaN(gbpPrice)) {
    localStorage.removeItem(key);
  } else {
    localStorage.setItem(key, JSON.stringify({ gbp: parseFloat(gbpPrice) }));
  }
};

const getManualUKPrice = (brand, name, perBox) => {
  try {
    const key = `ukPrice_${brand}_${name}_${perBox}`;
    const stored = localStorage.getItem(key);
    if (stored) {
      return JSON.parse(stored).gbp;
    }
  } catch (e) {}
  return null;
};

const clearManualUKPrice = (brand, name, perBox) => {
  const key = `ukPrice_${brand}_${name}_${perBox}`;
  localStorage.removeItem(key);
};

// Onwards data
const initialOnwards = [
  { id: 1, datePurchased: '2025-11-05', received: true, brand: 'Trinidad', name: 'Topes', qty: 1, perBox: 12, costUSD: 504, salePriceGBP: null, salePriceUSD: 504, profitUSD: 0, soldTo: 'To Eduard Kourani', type: 'sold-at-cost' },
  { id: 2, datePurchased: '2025-11-20', received: true, brand: 'Cohiba', name: 'Vistosos', qty: 1, perBox: 10, costUSD: 1900, salePriceGBP: 2350, salePriceUSD: 3149, profitUSD: 1249, soldTo: 'By Eduard Kourani', type: 'sold' },
  { id: 3, datePurchased: '2025-11-20', received: true, brand: 'Trinidad', name: 'Robusto Extra', qty: 1, perBox: 12, costUSD: 660, salePriceGBP: 850, salePriceUSD: 1139, profitUSD: 479, soldTo: 'By Eduard Kourani', type: 'sold' },
  { id: 4, datePurchased: '2026-01-05', received: false, brand: 'Cohiba', name: 'Vistosos', qty: 1, perBox: 10, costUSD: 1900, salePriceGBP: null, salePriceUSD: null, profitUSD: null, soldTo: '', type: 'pending' },
  { id: 5, datePurchased: '2026-01-20', received: false, brand: 'Partagas', name: 'Linea Maestra Origen', qty: 1, perBox: 20, costUSD: 1200, salePriceGBP: null, salePriceUSD: 1200, profitUSD: 0, soldTo: 'By Ash, as a gift to Pearse', type: 'sold-at-cost' },
];

// Box data
const initialBoxes = [
  { id: 1, boxNum: '1', brand: 'Montecristo', name: 'Brilllantes', datePurchased: '2025-07-17', received: true, perBox: 18, priceUSD: 1200, status: 'Immediate', dateOfBox: '', code: '', location: 'London', consumed: 6, remaining: 12 },
  { id: 2, boxNum: '2.1', brand: 'Trinidad', name: 'Robusto Extra', datePurchased: '2025-07-17', received: true, perBox: 12, priceUSD: 650, status: 'Immediate', dateOfBox: '', code: '', location: 'London', consumed: 12, remaining: 0 },
  { id: 3, boxNum: '2.2', brand: 'Trinidad', name: 'Robusto Extra', datePurchased: '2025-07-17', received: true, perBox: 12, priceUSD: 650, status: 'Immediate', dateOfBox: '', code: '', location: 'London', consumed: 12, remaining: 0 },
  { id: 4, boxNum: '3', brand: 'Montecristo', name: 'Leyendas', datePurchased: '2025-09-02', received: true, perBox: 20, priceUSD: 900, status: 'Immediate', dateOfBox: '', code: '', location: 'London', consumed: 18, remaining: 2 },
  { id: 5, boxNum: '4', brand: 'Hoyo de Monterrey', name: 'Destinos', datePurchased: '2025-09-02', received: true, perBox: 20, priceUSD: 1400, status: 'Combination', dateOfBox: '', code: '', location: 'London', consumed: 6, remaining: 14 },
  { id: 6, boxNum: '5', brand: 'Ramon Allones', name: 'Absolutos', datePurchased: '2025-11-05', received: true, perBox: 20, priceUSD: 1500, status: 'Combination', dateOfBox: '', code: '', location: 'London', consumed: 4, remaining: 16 },
  { id: 7, boxNum: '6', brand: 'Hoyo de Monterrey', name: 'Double Corona', datePurchased: '2025-11-05', received: true, perBox: 50, priceUSD: 1750, status: 'Combination', dateOfBox: '2025-05-01', code: 'OEG', location: 'Cayman', consumed: 6, remaining: 44 },
  { id: 8, boxNum: '7', brand: 'Trinidad', name: 'Robusto Extra', datePurchased: '2025-11-05', received: true, perBox: 12, priceUSD: 660, status: 'Immediate', dateOfBox: '2025-06-01', code: 'BRT', location: 'Cayman', consumed: 2, remaining: 10 },
  { id: 9, boxNum: '8', brand: 'Bolivar', name: 'New Gold Medal', datePurchased: '2025-11-05', received: true, perBox: 10, priceUSD: 500, status: 'Ageing', dateOfBox: '2026-06-25', code: 'EBP', location: 'Cayman', consumed: 0, remaining: 10 },
  { id: 10, boxNum: '9', brand: 'Partagas', name: 'Lusitinas', datePurchased: '2025-11-05', received: true, perBox: 10, priceUSD: 375, status: 'Combination', dateOfBox: '2026-07-25', code: 'UAR', location: 'Cayman', consumed: 4, remaining: 6 },
  { id: 11, boxNum: '10.1', brand: 'Cohiba', name: 'Vistosos', datePurchased: '2026-01-05', received: false, perBox: 10, priceUSD: 1900, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 10 },
  { id: 12, boxNum: '10.2', brand: 'Cohiba', name: 'Vistosos', datePurchased: '2026-01-05', received: false, perBox: 10, priceUSD: 1900, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 10 },
  { id: 13, boxNum: '10.3', brand: 'Cohiba', name: 'Vistosos', datePurchased: '2026-01-05', received: false, perBox: 10, priceUSD: 1900, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 10 },
  { id: 14, boxNum: '11.1', brand: 'Cohiba', name: 'Siglo VI', datePurchased: '2026-01-05', received: false, perBox: 25, priceUSD: 2500, status: 'Ageing', dateOfBox: '2025-01-01', code: 'GES', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 15, boxNum: '11.2', brand: 'Cohiba', name: 'Siglo VI', datePurchased: '2026-01-05', received: false, perBox: 25, priceUSD: 2500, status: 'Ageing', dateOfBox: '2025-01-01', code: 'GES', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 16, boxNum: '12', brand: 'Cohiba', name: 'Maduro 5 Genios', datePurchased: '2026-01-05', received: false, perBox: 25, priceUSD: 2500, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 17, boxNum: '13', brand: 'Cohiba', name: 'Maduro 5 Magicos', datePurchased: '2026-01-05', received: false, perBox: 25, priceUSD: 2000, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 18, boxNum: '14.1', brand: 'Cohiba', name: 'Behike 52', datePurchased: '2026-01-05', received: false, perBox: 10, priceUSD: 2500, status: 'Ageing', dateOfBox: '2026-11-24', code: 'GES', location: 'Cayman', consumed: 0, remaining: 10 },
  { id: 19, boxNum: '14.2', brand: 'Cohiba', name: 'Behike 52', datePurchased: '2026-01-05', received: false, perBox: 10, priceUSD: 2500, status: 'Ageing', dateOfBox: '2026-11-24', code: 'GES', location: 'Cayman', consumed: 0, remaining: 10 },
  { id: 20, boxNum: '15', brand: 'Trinidad', name: 'Robusto Extra', datePurchased: '2026-01-05', received: false, perBox: 12, priceUSD: 720, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 12 },
  { id: 21, boxNum: '16', brand: 'Partagas', name: 'Linea Maestra Maestros', datePurchased: '2026-01-05', received: false, perBox: 20, priceUSD: 1300, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 20 },
  { id: 22, boxNum: '17', brand: 'Hoyo de Monterrey', name: 'Petit Robustos', datePurchased: '2026-01-09', received: false, perBox: 25, priceUSD: 550, status: 'Immediate', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 23, boxNum: '18', brand: 'Cohiba', name: 'Siglo I', datePurchased: '2026-01-09', received: false, perBox: 25, priceUSD: 850, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 24, boxNum: '19', brand: 'Cohiba', name: 'Medio Siglo', datePurchased: '2026-01-09', received: false, perBox: 25, priceUSD: 1500, status: 'Combination', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 25, boxNum: '20', brand: 'Cohiba', name: 'Behike 56', datePurchased: '2026-01-09', received: false, perBox: 10, priceUSD: 3500, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 10 },
  { id: 26, boxNum: '21', brand: 'Trinidad', name: 'Esmerelda', datePurchased: '2026-01-09', received: false, perBox: 12, priceUSD: 500, status: 'Ageing', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 12 },
  { id: 27, boxNum: '22', brand: 'Cohiba', name: 'Siglo VI', datePurchased: '2026-01-20', received: false, perBox: 25, priceUSD: 2750, status: 'Combination', dateOfBox: '', code: 'GES', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 28, boxNum: '23', brand: 'Cohiba', name: 'Medio Siglo', datePurchased: '2026-01-20', received: false, perBox: 25, priceUSD: 1500, status: 'Combination', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 29, boxNum: '24', brand: 'Cohiba', name: 'Lanceros', datePurchased: '2026-01-20', received: false, perBox: 25, priceUSD: 2500, status: 'Ageing', dateOfBox: '2023-11-23', code: 'RSG', location: 'Cayman', consumed: 0, remaining: 25 },
  { id: 30, boxNum: '25', brand: 'Cohiba', name: 'Siglo VI', datePurchased: '2026-01-20', received: false, perBox: 10, priceUSD: 1200, status: 'Combination', dateOfBox: '', code: '', location: 'Cayman', consumed: 0, remaining: 10 },
];

// Brand Logo Component - DISABLED (logos removed for cleaner display)
const BrandLogo = ({ brand, size = 50 }) => {
  return null;
};

// Group boxes by brand+name
const groupBoxes = (boxes) => {
  const groups = {};
  boxes.forEach(box => {
    const key = `${box.brand}|${box.name}`;
    if (!groups[key]) groups[key] = { brand: box.brand, name: box.name, boxes: [] };
    groups[key].boxes.push(box);
  });
  return Object.values(groups);
};

// Cigar Group Card
const CigarGroupCard = ({ group, onClick, maxLengths, showCigarCount = true, isFinishedView = false }) => {
  const { brand, name, boxes } = group;
  const s = brandStyles[brand] || brandStyles['Cohiba'];
  const totalRemaining = boxes.reduce((sum, b) => sum + b.remaining, 0);
  const totalOriginal = boxes.reduce((sum, b) => sum + b.perBox, 0);
  const totalBoxes = boxes.length;
  const nonEmptyBoxes = boxes.filter(b => b.remaining > 0).length;
  const isFinished = totalRemaining === 0;
  
  // Calculate font sizes based on max lengths
  const brandSize = maxLengths?.maxBrand > 18 ? '1.1rem' : maxLengths?.maxBrand > 12 ? '1.3rem' : '1.5rem';
  const nameSize = maxLengths?.maxName > 25 ? '1rem' : maxLengths?.maxName > 18 ? '1.15rem' : '1.25rem';
  
  return (
    <div onClick={onClick} className="relative cursor-pointer active:scale-98 transition-transform">
      <div className="relative rounded-xl overflow-hidden" style={{
        background: s.bg, 
        border: 'none', 
        opacity: 1,
        boxShadow: 'inset 0 1px 2px rgba(255,255,255,0.2), inset 0 -1px 2px rgba(0,0,0,0.08)',
        borderTop: '1px solid rgba(255,255,255,0.12)',
        backgroundImage: `${s.bg}, url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='4' height='4'%3E%3Crect width='4' height='4' fill='%23000' fill-opacity='0.03'/%3E%3Crect x='0' y='0' width='2' height='2' fill='%23fff' fill-opacity='0.02'/%3E%3C/svg%3E")`,
      }}>
        <div className="p-3">
          <div className="text-center mb-1">
            <div className="font-bold tracking-wide" style={{ color: s.text, fontFamily: 'tt-ricordi-allegria, Georgia, serif', fontSize: brandSize }}>{brand}</div>
          </div>
          <div className="text-center mb-3">
            <div className="font-medium" style={{ color: s.text, opacity: 0.9, fontSize: nameSize }}>{name}</div>
          </div>
         <div className="rounded overflow-hidden mb-2" style={{ background: 'rgba(184,132,76,0.8)' }}>
            {(() => {
              // Sort boxes chronologically by purchase date, then open boxes last if same date
              const sortedBoxes = [...boxes].sort((a, b) => {
                const dateA = a.datePurchased ? new Date(a.datePurchased).getTime() : 0;
                const dateB = b.datePurchased ? new Date(b.datePurchased).getTime() : 0;
                if (dateA !== dateB) return dateA - dateB;
                // Same date: open boxes go to the right
                const aIsOpen = a.remaining > 0 && a.remaining < a.perBox;
                const bIsOpen = b.remaining > 0 && b.remaining < b.perBox;
                if (aIsOpen && !bIsOpen) return 1;
                if (!aIsOpen && bIsOpen) return -1;
                return 0;
              });
              return [...Array(Math.ceil(sortedBoxes.length / 6) || 1)].map((_, rowIdx) => (
                <div key={rowIdx} className="h-5 flex gap-0.5 p-1 items-end">
                  {[...Array(6)].map((_, i) => {
                    const boxIndex = rowIdx * 6 + i;
                    const box = sortedBoxes[boxIndex];
                    const isEmpty = !box;
                    const isFull = box && box.remaining === box.perBox;
                    const isOpen = box && box.remaining > 0 && box.remaining < box.perBox;
                    const isEmptyBox = box && box.remaining === 0;
                    return <div key={i} className="flex-1 rounded-sm" style={{ 
                      height: isEmpty ? '0%' : (isFull || isOpen || isFinishedView) ? '100%' : '20%', 
                      background: isFinishedView ? '#1a1a1a' : (isFull ? '#6B1E1E' : isOpen ? '#6B1E1E' : 'rgba(0,0,0,0.3)'),
                      border: isOpen && !isFinishedView ? '2px solid #F5DEB3' : 'none',
                      visibility: isEmpty ? 'hidden' : 'visible'
                    }} />;
                  })}
                </div>
              ));
            })()}
          </div>
          {showCigarCount && (
            <div className="flex justify-between items-center text-sm">
              <span className="font-bold" style={{ color: s.text }}>{totalRemaining} total</span>
              <span style={{ color: s.text, opacity: 0.7 }}>{nonEmptyBoxes} box{nonEmptyBoxes !== 1 ? 'es' : ''}</span>
            </div>
          )}
        </div>
        {(() => {
          const openBoxes = boxes.filter(b => b.remaining > 0 && b.remaining < b.perBox);
          const openCount = openBoxes.reduce((sum, b) => sum + b.remaining, 0);
          return openBoxes.length > 0 ? (
            <div className="absolute -top-1 -right-1 w-7 h-7 rounded-full flex items-center justify-center font-bold shadow-lg" 
              style={{ background: '#6B1E1E', color: '#fff', fontSize: 12 }}>{openCount}</div>
          ) : null;
        })()}
        {isFinished && !isFinishedView && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none" style={{ background: 'rgba(0,0,0,0.7)' }}>
            <span className="text-sm px-3 py-1 rounded" style={{ background: '#333', color: '#888' }}>Finished</span>
          </div>
        )}
      </div>
    </div>
  );
};

// Onwards Card
const OnwardsCard = ({ item, fmtCurrency }) => {
  const isSold = item.type === 'sold';
  const isSoldAtCost = item.type === 'sold-at-cost';
  const isSoldAtLoss = item.type === 'sold-at-loss';
  const isPending = item.type === 'pending';
  
  const getStatusStyle = () => {
    if (isSold) return { background: '#2d5a3d', color: '#90EE90' };
    if (isSoldAtLoss) return { background: '#5a2d2d', color: '#ff9090' };
    if (isSoldAtCost) return { background: '#4a4a3a', color: '#d4d4a0' };
    return { background: '#5a4a2d', color: '#ffd700' };
  };
  
  const getStatusText = () => {
    if (isSold) return `+${fmtCurrency(item.profitUSD)}`;
    if (isSoldAtLoss) return fmtCurrency(item.profitUSD);
    if (isSoldAtCost) return 'At cost';
    return 'Pending';
  };
  
  return (
    <div className="p-4 rounded-lg" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
      {/* Header: Brand/Name left, Status badge right */}
      <div className="flex justify-between items-start mb-3 pb-3 border-b" style={{ borderColor: '#6B1E1E' }}>
        <div>
          <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{item.brand}</div>
          <div className="text-base font-medium" style={{ color: '#1a120b' }}>{item.name}</div>
          <div className="text-sm mt-1" style={{ color: 'rgba(26,18,11,0.5)' }}>{item.qty} box of {item.perBox}</div>
        </div>
        <div 
          className="px-3 py-1.5 rounded-full text-sm font-bold"
          style={getStatusStyle()}
        >
          {getStatusText()}
        </div>
      </div>
      
      {/* Transaction details */}
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: 'rgba(26,18,11,0.5)' }}>Purchased</span>
          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>{fmt.date(item.datePurchased)} • {fmtCurrency(item.costUSD)}</span>
        </div>
        
        {(isSold || isSoldAtCost || isSoldAtLoss) && (
          <div className="flex justify-between items-center">
            <span className="text-sm" style={{ color: 'rgba(26,18,11,0.5)' }}>Sold</span>
            <span className="text-sm font-medium" style={{ color: '#1a120b' }}>
              {item.saleDate ? `${fmt.date(item.saleDate)} • ` : ''}{fmtCurrency(item.salePriceUSD)}
            </span>
          </div>
        )}
        
        {item.soldTo && (
          <div className="text-sm italic pt-1" style={{ color: 'rgba(26,18,11,0.6)' }}>{item.soldTo}</div>
        )}
      </div>
    </div>
  );
};

// Edit Box Modal
const EditBoxModal = ({ box, onClose, onSave, availableLocations = [] }) => {
  const [brand, setBrand] = useState(box.brand || '');
  const [name, setName] = useState(box.name || '');
  const [boxNum, setBoxNum] = useState(box.boxNum || '');
  const [perBox, setPerBox] = useState(box.perBox || '');
  const [price, setPrice] = useState(box.price || '');
  const [priceCurrency, setPriceCurrency] = useState(box.currency || 'USD');
  const [datePurchased, setDatePurchased] = useState(box.datePurchased || '');
  const [location, setLocation] = useState(box.location || '');
  const [newLocation, setNewLocation] = useState('');
  const [status, setStatus] = useState(box.status || 'Ageing');
  const [received, setReceived] = useState(box.received || false);
  const [code, setCode] = useState(box.code || '');
  const [dateOfBox, setDateOfBox] = useState(box.dateOfBox || '');
  const [ringGauge, setRingGauge] = useState(box.ringGauge || '');
  const [length, setLength] = useState(box.length || '');
  const [vitola, setVitola] = useState(box.vitola || '');
  const [consumed, setConsumed] = useState(box.consumed || 0);
  const [remaining, setRemaining] = useState(box.remaining || 0);

  useEffect(() => {
    const perBoxNum = parseInt(perBox) || 0;
    const consumedNum = parseInt(consumed) || 0;
    const remainingNum = parseInt(remaining) || 0;
    const maxRemaining = perBoxNum - consumedNum;
    
    if (remainingNum > maxRemaining && perBoxNum > 0) {
      setRemaining(Math.max(0, maxRemaining));
    }
  }, [perBox, consumed]);
  
  const [isSaving, setIsSaving] = useState(false);
  
  const allLocations = [...new Set([...availableLocations, box.location].filter(Boolean))];
  
  const handleSave = async () => {
    setIsSaving(true);
    const finalLocation = location === '__new__' ? newLocation : location;
    
    const updatedData = {
      brand,
      name,
      boxNum,
      perBox: parseInt(perBox),
      price: parseFloat(price),
      currency: priceCurrency,
      datePurchased,
      location: finalLocation,
      status,
      received,
      code,
      dateOfBox,
      ringGauge,
      length,
      vitola,
      boxNotes: box.boxNotes || '',
      consumed: parseInt(consumed),
      remaining: parseInt(remaining),
    };
    
    console.log('Saving updatedData:', updatedData);
    await onSave(updatedData);
    setIsSaving(false);
  };
  
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4 py-8" onClick={onClose} style={{ background: 'rgba(0,0,0,0.9)' }}>
      <div className="w-full max-w-md rounded-2xl max-h-[90vh] overflow-y-auto" style={{ background: '#1a1a1a', border: '1px solid #333', scrollbarWidth: 'none', msOverflowStyle: 'none' }} onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 z-10 p-4 flex justify-between items-center" style={{ background: '#1a1a1a', borderBottom: '1px solid #333' }}>
          <h3 className="text-lg font-semibold" style={{ color: '#F5DEB3' }}>Edit Box</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: '#333', color: '#888' }}>×</button>
        </div>
        
        <div className="p-4 space-y-4">
          {/* Date Purchased and Price */}
          <div className="grid grid-cols-2 gap-3">
            <div style={{ overflow: 'hidden' }}>
              <label className="text-xs text-gray-500 block mb-2">Date Purchased</label>
              <input type="date" value={datePurchased} onChange={e => setDatePurchased(e.target.value)} className="w-full px-2 py-2 rounded-lg" style={{ background: '#252525', border: '1px solid #333', color: '#fff', fontSize: '14px', WebkitAppearance: 'none', minHeight: '42px' }} />
            </div>
            <div className="min-w-0">
              <label className="text-xs text-gray-500 block mb-2">Price</label>
              <div className="flex gap-1">
                <select 
                  value={priceCurrency} 
                  onChange={e => setPriceCurrency(e.target.value)}
                  className="px-2 py-2 rounded-lg text-sm flex-shrink-0"
                  style={{ background: '#252525', border: '1px solid #333', color: '#fff', width: '70px' }}
                >
                  {CURRENCIES.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <input type="number" value={price} onChange={e => setPrice(e.target.value)} placeholder="e.g. 2500" className="flex-1 min-w-0 px-2 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} />
              </div>
            </div>
          </div>
          
          {/* Brand */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Brand</label>
            <input 
              type="text" 
              value={brand} 
              onChange={e => setBrand(e.target.value)} 
              className="w-full px-3 py-2 rounded-lg text-base" 
              style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
            />
          </div>
          
          {/* Cigar Name */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Cigar Name</label>
            <input 
              type="text" 
              value={name} 
              onChange={e => setName(e.target.value)} 
              className="w-full px-3 py-2 rounded-lg text-base" 
              style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
            />
          </div>
          
          {/* Received */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Received</label>
            <button 
              onClick={() => setReceived(!received)} 
              className="w-full px-3 py-2 rounded-lg text-base text-left" 
              style={{ background: received ? '#1c3a1c' : '#252525', border: '1px solid #333', color: received ? '#99ff99' : '#888' }}
            >
              {received ? 'Yes' : 'No'}
            </button>
          </div>
          
          {/* Ring Gauge and Length */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Ring Gauge</label>
              <input 
                type="text" 
                value={ringGauge} 
                onChange={e => setRingGauge(e.target.value)} 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-2">Length (inches)</label>
              <input 
                type="text" 
                value={length} 
                onChange={e => setLength(e.target.value)} 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
          </div>
          
          {/* Vitola Notes */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Vitola Notes</label>
            <input 
              type="text" 
              value={vitola} 
              onChange={e => setVitola(e.target.value)} 
              className="w-full px-3 py-2 rounded-lg text-base" 
              style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
            />
          </div>
          
          {/* Box Number and Cigars Per Box */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Box Number</label>
              <input 
                type="text" 
                value={boxNum} 
                onChange={e => setBoxNum(e.target.value)} 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-2">Cigars Per Box</label>
              <input 
                type="number" 
                value={perBox} 
                onChange={e => {
                  const val = parseInt(e.target.value) || 0;
                  const consumedNum = parseInt(consumed) || 0;
                  setPerBox(Math.max(val, consumedNum));
                }}
                min={consumed}
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
          </div>
          
          {/* Consumed and Remaining */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Consumed</label>
              <input 
                type="number" 
                value={consumed} 
                onChange={e => {
                  const val = parseInt(e.target.value) || 0;
                  const max = parseInt(perBox) || 0;
                  const newConsumed = Math.min(Math.max(0, val), max);
                  setConsumed(newConsumed);
                  setRemaining(max - newConsumed);
                }}
                max={perBox}
                min={0}
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-2">Remaining</label>
              <input 
                type="number" 
                value={remaining} 
                onChange={e => {
                  const val = parseInt(e.target.value) || 0;
                  const max = parseInt(perBox) || 0;
                  const newRemaining = Math.min(Math.max(0, val), max);
                  setRemaining(newRemaining);
                  setConsumed(max - newRemaining);
                }}
                max={perBox}
                min={0} 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
          </div>
          
          {/* Factory Code and Release Date */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Factory Code</label>
              <input 
                type="text" 
                value={code} 
                onChange={e => setCode(e.target.value.toUpperCase())} 
                placeholder="e.g. GES MAR 24"
                autoCapitalize="characters"
                className="w-full px-3 py-2 rounded-lg text-base font-mono" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff', textTransform: 'uppercase' }} 
              />
            </div>
            <div style={{ overflow: 'hidden' }}>
              <label className="text-xs text-gray-500 block mb-2">Release Date</label>
              <input 
                type="month" 
                value={dateOfBox ? dateOfBox.substring(0, 7) : ''} 
                onChange={e => setDateOfBox(e.target.value)} 
                className="w-full px-2 py-2 rounded-lg" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff', fontSize: '14px', WebkitAppearance: 'none', minHeight: '42px' }} 
              />
            </div>
          </div>
          
          {/* Location and Status */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Location</label>
              <select 
                value={location} 
                onChange={e => setLocation(e.target.value)} 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }}
              >
                {allLocations.map(l => <option key={l} value={l}>{l}</option>)}
                <option value="__new__">— New Location —</option>
              </select>
              {location === '__new__' && (
                <input 
                  type="text" 
                  value={newLocation} 
                  onChange={e => setNewLocation(e.target.value)} 
                  placeholder="Enter new location..." 
                  className="w-full px-3 py-2 rounded-lg text-base mt-2" 
                  style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
                />
              )}
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-2">Status</label>
              <select 
                value={status} 
                onChange={e => setStatus(e.target.value)} 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }}
              >
                <option value="Ageing">Ageing</option>
                <option value="Immediate">On Rotation</option>
                <option value="Combination">Assortment</option>
              </select>
            </div>
          </div>
          
          {/* Save and Discard Buttons */}
          <div className="flex gap-3 mt-4">
            <button 
              onClick={onClose}
              className="flex-1 py-3 rounded-lg font-semibold"
              style={{ background: '#252525', color: '#888', border: '1px solid #444' }}
            >
              Discard
            </button>
            <button 
              onClick={handleSave} 
              disabled={isSaving}
              className="flex-1 py-3 rounded-lg font-semibold" 
              style={{ background: isSaving ? '#333' : '#F5DEB3', color: isSaving ? '#666' : '#1a120b' }}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// Box Detail Modal
  const BoxDetailModal = ({ boxes, initialBoxIndex = 0, onClose, fmtCurrency, fmtCurrencyWithOriginal, fmtFromGBP, onDelete, onEdit, isSignedIn, availableLocations = [], baseCurrency, fxRates }) => {
  const [selectedIdx, setSelectedIdx] = useState(initialBoxIndex);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showNotesModal, setShowNotesModal] = useState(false);
  const [noteText, setNoteText] = useState('');
  
  useEffect(() => {
    setSelectedIdx(initialBoxIndex);
  }, [initialBoxIndex]);
  
  const box = boxes[selectedIdx];
  const s = brandStyles[box.brand] || brandStyles['Cohiba'];
  const market = getMarket(box.brand, box.name, box.perBox);
  const boxPriceInBase = convertCurrency(box.price || 0, box.currency || 'USD', baseCurrency, fxRates);
  const marketGBP = market?.gbp || null;
  const marketInBase = convertCurrency(marketGBP, 'GBP', baseCurrency, fxRates);
  const savingsInBase = marketInBase - boxPriceInBase;

  const handleDelete = async () => {
    if (!onDelete) return;
    setIsDeleting(true);
    const success = await onDelete(box);
    setIsDeleting(false);
    if (success) {
      // If there are other boxes in this group, stay open and switch to another box
      if (boxes.length > 1) {
        // If we deleted the last box in the list, go to the previous one
        if (selectedIdx >= boxes.length - 1) {
          setSelectedIdx(Math.max(0, selectedIdx - 1));
        }
        // The parent will refresh the boxes array, so we just need to reset delete confirm
        setShowDeleteConfirm(false);
      } else {
        // No other boxes, close the modal
        onClose();
      }
    }
  };
  
  // Calculate box age
const calculateAge = (dateStr) => {
  if (!dateStr) return null;
  
  // Parse YYYY-MM format directly to avoid timezone issues
  const match = dateStr.match(/^(\d{4})-(\d{2})$/);
  if (match) {
    const boxYear = parseInt(match[1]);
    const boxMonth = parseInt(match[2]);
    const now = new Date();
    const nowYear = now.getFullYear();
    const nowMonth = now.getMonth() + 1;
    
    let totalMonths = (nowYear - boxYear) * 12 + (nowMonth - boxMonth);
    const years = Math.floor(totalMonths / 12);
    const months = totalMonths % 12;
    return { years, months };
  }
  
  // Fallback for other date formats
  const boxDate = new Date(dateStr);
  const now = new Date();
  const diffMs = now - boxDate;
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const years = Math.floor(diffDays / 365);
  const months = Math.floor((diffDays % 365) / 30);
  return { years, months };
};

const boxAgeData = calculateAge(box.dateOfBox);
const isFullBox = box.remaining === box.perBox;
  
  return (
    <>
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-8" onClick={onClose} style={{ background: 'rgba(0,0,0,0.9)' }}>
      <div className="w-full max-w-md rounded-2xl max-h-[85vh] overflow-y-auto" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', border: '1px solid #333', scrollbarWidth: 'none', msOverflowStyle: 'none' }} onClick={e => e.stopPropagation()}>
        
        {/* Header */}
        <div className="sticky top-0 z-10 p-4 flex justify-between items-start" style={{ background: '#1a120b', borderBottom: '2px solid #6B1E1E' }}>
          <div>
            <h3 className="text-4xl font-bold" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{box.brand}</h3>
            <p className="text-2xl" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif', opacity: 0.9 }}>{box.name}</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'rgba(245,222,179,0.1)', color: '#F5DEB3', fontSize: '1.25rem' }}>×</button>
        </div>
        
{/* Box Selector Buttons */}
<div className="px-4 pt-3 pb-2 flex gap-2 overflow-x-auto items-center" style={{ background: 'rgba(184,132,76,0.8)', scrollbarWidth: 'none', msOverflowStyle: 'none' }}>
  {[...boxes].sort((a, b) => {
    const dateA = a.datePurchased ? new Date(a.datePurchased).getTime() : 0;
    const dateB = b.datePurchased ? new Date(b.datePurchased).getTime() : 0;
    if (dateA !== dateB) return dateA - dateB;
    const aIsOpen = a.remaining > 0 && a.remaining < a.perBox;
    const bIsOpen = b.remaining > 0 && b.remaining < b.perBox;
    if (aIsOpen && !bIsOpen) return 1;
    if (!aIsOpen && bIsOpen) return -1;
    return 0;
  }).map((b) => (
    <div key={b.id} className="flex flex-col items-center gap-1.5">
      <button 
        onClick={() => setSelectedIdx(boxes.findIndex(box => box.id === b.id))} 
        className="flex items-center justify-center"
        style={{
          width: '72px',
          height: '32px',
          background: '#6B1E1E',
          color: '#F5DEB3',
          borderRadius: '4px',
          fontFamily: 'tt-ricordi-allegria, Georgia, serif',
          fontSize: '14px',
          border: b.remaining > 0 && b.remaining < b.perBox ? '3px solid #F5DEB3' : '3px solid transparent',
          boxSizing: 'border-box'
        }}
      >
        Box {b.boxNum}
      </button>
      <div 
        className="w-2 h-2 rounded-full"
        style={{ 
          background: boxes.findIndex(box => box.id === b.id) === selectedIdx ? '#1a120b' : 'transparent'
        }}
      />
    </div>
  ))}
</div>
        
        <div className="p-4 pb-6">
          
          {/* Box Status Row */}
<div className="py-4 border-b-2" style={{ borderColor: '#6B1E1E' }}>
  <div className="flex justify-around">
    <div className="text-center">
      <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box of</div>
      <div className="text-4xl font-medium" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{box.perBox}</div>
    </div>
    <div className="text-center">
      <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Remaining</div>
      <div className="text-4xl font-medium" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{box.remaining}</div>
    </div>
    <div className="text-center">
      <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Age</div>
      <div className="text-4xl font-medium" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>
        {boxAgeData ? (
          <>
            {boxAgeData.years > 0 && <><span>{boxAgeData.years}</span><span className="text-lg">{boxAgeData.years === 1 ? ' yr' : ' yrs'}</span></>}
            {boxAgeData.months > 0 && <><span>{boxAgeData.years > 0 ? ' ' : ''}{boxAgeData.months}</span><span className="text-lg"> mo</span></>}
            {boxAgeData.years === 0 && boxAgeData.months === 0 && <span className="text-lg">New</span>}
          </>
        ) : '–'}
      </div>
    </div>
  </div>
</div>

{/* Status */}
<div className="py-4 border-b-2" style={{ borderColor: '#6B1E1E' }}>
  <div className="flex justify-between items-start">
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Status</span>
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{getStatusDisplay(box.status)}</span>
  </div>
  {!box.received && (
    <div className="text-right">
      <span className="text-sm font-medium" style={{ color: '#6B1E1E' }}>(Yet to be received)</span>
    </div>
  )}
</div>

          {/* Pricing Row */}
<div className="py-4 border-b-2" style={{ borderColor: '#6B1E1E' }}>
  <div className="flex justify-between items-center mb-3">
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Date of Purchase</span>
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{fmt.date(box.datePurchased)}</span>
  </div>
  <div className="flex justify-between items-center mb-3">
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Your Cost</span>
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{fmtCurrencyWithOriginal(box.price, box.currency)}</span>
  </div>
  <div className="flex justify-between items-center mb-3">
  <span className="text-lg font-medium" style={{ color: '#1a120b' }}>UK Market</span>
  <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{marketGBP ? fmtFromGBP(marketGBP) : 'No Data'}</span>
  </div>
  {savingsInBase > 0 && (
    <div className="flex justify-between items-center">
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Savings</span>
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{fmtFromGBP(savingsInBase)} ({Math.round(savingsInBase/marketInBase*100)}%)</span>
    </div>
  )}
</div>

          {/* Details Section */}
<div className="py-4 border-b-2" style={{ borderColor: '#6B1E1E' }}>
  {box.ringGauge && (
    <div className="flex justify-between items-center mb-3">
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Ring Gauge</span>
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{box.ringGauge}</span>
    </div>
  )}
  {box.length && (
    <div className="flex justify-between items-center mb-3">
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Length</span>
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{box.length}"</span>
    </div>
  )}
  {box.vitola && (
    <div className="flex justify-between items-start mb-3">
      <span className="text-lg font-medium flex-shrink-0" style={{ color: '#1a120b' }}>Vitola</span>
      <span className="text-lg font-medium text-right" style={{ color: '#1a120b', maxWidth: '50%' }}>{box.vitola}</span>
    </div>
  )}
  <div className="flex justify-between items-center mb-3">
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Release Date</span>
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{box.dateOfBox ? fmt.monthYear(box.dateOfBox) : 'Unknown'}</span>
  </div>
  {box.code && (
    <div className="flex justify-between items-center mb-3">
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Factory Code</span>
      <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{box.code}</span>
    </div>
  )}
  <div className="flex justify-between items-center mb-3">
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Box ID</span>
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{box.boxNum}</span>
  </div>
  <div className="flex justify-between items-center">
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Location</span>
    <span className="text-lg font-medium" style={{ color: '#1a120b' }}>{box.location}</span>
  </div>
</div>

{/* Notes Section */}
<div className="py-4 border-b-2" style={{ borderColor: '#6B1E1E' }}>
  {box.boxNotes ? (
    <div>
      <div className="flex justify-between items-start">
        <span className="text-lg font-medium" style={{ color: '#1a120b' }}>Notes</span>
        <button 
          onClick={() => { setNoteText(box.boxNotes || ''); setShowNotesModal(true); }}
          className="text-lg font-medium"
          style={{ color: '#1a120b', background: 'none', border: 'none', textDecoration: 'underline', cursor: 'pointer' }}
        >
          Edit
        </button>
      </div>
      <p className="text-lg font-medium mt-2" style={{ color: '#1a120b' }}>{box.boxNotes}</p>
    </div>
  ) : (
    <button 
      onClick={() => { setNoteText(''); setShowNotesModal(true); }}
      className="text-lg font-medium w-full text-left"
      style={{ color: '#1a120b', background: 'none', border: 'none', cursor: 'pointer' }}
    >
      Add Note
    </button>
  )}
</div>

          {/* Action Buttons */}
          {isSignedIn && !showDeleteConfirm && (
            <div className="flex gap-2 pt-4">
              <button
                onClick={() => setShowEditModal(true)}
                className="flex-1 py-3 text-lg font-bold"
                style={{ background: '#1a120b', color: '#F5DEB3', borderRadius: '8px', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}
              >
                Edit
              </button>
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="flex-1 py-3 text-lg font-bold"
                style={{ background: '#6B1E1E', color: '#F5DEB3', borderRadius: '8px', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}
              >
                Delete
              </button>
            </div>
          )}
          {showDeleteConfirm && (
            <div className="pt-4">
              <p className="text-lg font-bold mb-3" style={{ color: '#6B1E1E', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Delete this box?</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  className="flex-1 py-3 text-lg font-bold"
                  style={{ background: 'rgba(26,18,11,0.2)', color: '#1a120b', borderRadius: '8px', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  className="flex-1 py-3 text-lg font-bold"
                  style={{ background: '#6B1E1E', color: '#F5DEB3', borderRadius: '8px', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}
                >
                  {isDeleting ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      {/* Notes Modal */}
{showNotesModal && (
  <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setShowNotesModal(false)} style={{ background: 'rgba(0,0,0,0.9)' }}>
    <div className="w-full max-w-sm mx-4 rounded-xl p-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }} onClick={e => e.stopPropagation()}>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-xl font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>
          {box.boxNotes ? 'Edit Note' : 'Add Note'}
        </h3>
        <button onClick={() => setShowNotesModal(false)} className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'rgba(26,18,11,0.1)', color: '#1a120b', fontSize: '1.25rem' }}>×</button>
      </div>
      <textarea
        value={noteText}
        onChange={(e) => setNoteText(e.target.value)}
        className="w-full p-3 rounded-lg text-lg"
        style={{ background: 'rgba(26,18,11,0.1)', border: '1px solid rgba(26,18,11,0.2)', color: '#1a120b', minHeight: '150px', resize: 'vertical' }}
        placeholder="Enter your note..."
      />
     <button
  onClick={async () => {
    const success = await onEdit(box, { ...box, boxNotes: noteText });
    if (success) {
      setShowNotesModal(false);
    }
  }}
        className="w-full py-3 mt-4 text-lg font-bold rounded-lg"
        style={{ background: '#1a120b', color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}
      >
        Save
      </button>
    </div>
  </div>
)}
      
      {/* Edit Modal */}
      {showEditModal && (
        <EditBoxModal 
          box={box} 
          onClose={() => setShowEditModal(false)} 
          onSave={async (updatedData) => {
            const success = await onEdit(box, updatedData);
            if (success) {
              setShowEditModal(false);
            }
            return success;
          }}
          availableLocations={availableLocations}
        />
      )}
    </div>
    </>
  );
};

// Edit History Modal
const EditHistoryModal = ({ entry, index, onClose, onSave, onDelete }) => {
  // Format date for input (needs YYYY-MM-DD format)
  const formatDateForInput = (dateStr) => {
    if (!dateStr) return new Date().toISOString().split('T')[0];
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return new Date().toISOString().split('T')[0];
    return d.toISOString().split('T')[0];
  };
  
  const [date, setDate] = useState(formatDateForInput(entry.date));
  const [qty, setQty] = useState(entry.qty || 1);
  const [notes, setNotes] = useState(entry.notes || '');
  const [brand, setBrand] = useState(entry.brand || '');
  const [name, setName] = useState(entry.name || '');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  
  const isExternal = entry.boxNum === 'EXT' || entry.source === 'external';
  
  const handleSave = () => {
    // Format date to match sheet format (e.g., "23 Jan 2026")
    const formatDateForSheet = (dateStr) => {
      const d = new Date(dateStr);
      return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    };
    
    const newEntry = {
      ...entry,
      date: formatDateForSheet(date),
      qty,
      notes,
      brand: isExternal ? brand : entry.brand,
      name: isExternal ? name : entry.name,
    };
    onSave(index, entry, newEntry);
  };
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.9)' }}>
      <div className="w-full max-w-sm rounded-xl max-h-[85vh] overflow-y-auto" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', border: '1px solid #333', scrollbarWidth: 'none', msOverflowStyle: 'none' }}>
        <div className="sticky top-0 p-4 flex justify-between items-center" style={{ background: '#1a120b', borderBottom: '2px solid #6B1E1E' }}>
          <h3 className="text-lg font-bold" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Edit Log</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'rgba(245,222,179,0.1)', color: '#F5DEB3', fontSize: '1.25rem' }}>×</button>
        </div>
        
        <div className="p-4 space-y-4">
          {isExternal ? (
            <>
              <div>
                <label className="text-sm font-medium block mb-2" style={{ color: 'rgba(26,18,11,0.5)' }}>Brand</label>
                <input type="text" value={brand} onChange={e => setBrand(e.target.value)} className="w-full px-3 py-2 rounded-lg text-lg font-medium" style={{ background: 'rgba(26,18,11,0.1)', border: '1px solid rgba(26,18,11,0.2)', color: '#1a120b' }} />
              </div>
              <div>
                <label className="text-sm font-medium block mb-2" style={{ color: 'rgba(26,18,11,0.5)' }}>Cigar Name</label>
                <input type="text" value={name} onChange={e => setName(e.target.value)} className="w-full px-3 py-2 rounded-lg text-lg font-medium" style={{ background: 'rgba(26,18,11,0.1)', border: '1px solid rgba(26,18,11,0.2)', color: '#1a120b' }} />
              </div>
            </>
          ) : (
            <div className="p-3 rounded-lg" style={{ background: 'rgba(26,18,11,0.1)', border: '1px solid rgba(26,18,11,0.2)' }}>
              <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{entry.brand}</div>
              <div className="text-base font-medium" style={{ color: '#1a120b' }}>{entry.name}</div>
              <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box {entry.boxNum}</div>
            </div>
          )}
          
          <div>
            <label className="text-sm font-medium block mb-2" style={{ color: 'rgba(26,18,11,0.5)' }}>Date</label>
            <input type="date" value={date} onChange={e => setDate(e.target.value)} className="w-full px-3 py-2 rounded-lg text-lg font-medium" style={{ background: 'rgba(26,18,11,0.1)', border: '1px solid rgba(26,18,11,0.2)', color: '#1a120b' }} />
          </div>
          
          <div>
            <label className="text-sm font-medium block mb-2" style={{ color: 'rgba(26,18,11,0.5)' }}>Quantity</label>
            <div className="flex items-center gap-4">
              <button onClick={() => setQty(Math.max(1, qty - 1))} className="w-10 h-10 rounded-lg text-lg font-bold" style={{ background: '#1a120b', color: '#F5DEB3' }}>-</button>
              <span className="text-3xl font-medium" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif', minWidth: 40, textAlign: 'center' }}>{qty}</span>
              <button onClick={() => setQty(qty + 1)} className="w-10 h-10 rounded-lg text-lg font-bold" style={{ background: '#1a120b', color: '#F5DEB3' }}>+</button>
            </div>
          </div>
          
          <div>
            <label className="text-sm font-medium block mb-2" style={{ color: 'rgba(26,18,11,0.5)' }}>Notes (optional)</label>
            <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Tasting notes, occasion..." className="w-full px-3 py-2 rounded-lg text-lg font-medium resize-none" rows={2} style={{ background: 'rgba(26,18,11,0.1)', border: '1px solid rgba(26,18,11,0.2)', color: '#1a120b' }} />
          </div>
          
          {!showDeleteConfirm ? (
            <div className="flex gap-2 pt-2">
              <button onClick={handleSave} className="flex-1 py-3 rounded-lg text-lg font-bold" style={{ background: '#1a120b', color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>
                Save Changes
              </button>
              <button onClick={() => setShowDeleteConfirm(true)} className="flex-1 py-3 rounded-lg text-lg font-bold" style={{ background: '#6B1E1E', color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>
                Delete
              </button>
            </div>
          ) : (
            <div className="pt-2">
              <p className="text-lg font-bold mb-3" style={{ color: '#6B1E1E', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Delete this log?</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  className="flex-1 py-3 text-lg font-bold rounded-lg"
                  style={{ background: 'rgba(26,18,11,0.2)', color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}
                >
                  Cancel
                </button>
                <button
                  onClick={() => onDelete(index, entry)}
                  className="flex-1 py-3 text-lg font-bold rounded-lg"
                  style={{ background: '#6B1E1E', color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}
                >
                  Delete
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// Smoke Log Modal
const SmokeLogModal = ({ boxes, onClose, onLog }) => {
  const [source, setSource] = useState(null); // 'collection' or 'external'
  const [selectedBox, setSelectedBox] = useState(null);
  const [qty, setQty] = useState(1);
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [notes, setNotes] = useState('');
  const [externalBrand, setExternalBrand] = useState('');
  const [externalName, setExternalName] = useState('');
  
  const available = boxes.filter(b => b.remaining > 0).sort((a, b) => {
  if (a.brand !== b.brand) return a.brand.localeCompare(b.brand);
  if (a.name !== b.name) return a.name.localeCompare(b.name);
  return String(a.boxNum).localeCompare(String(b.boxNum), undefined, { numeric: true });
});
  
  const handleSubmit = () => {
    if (source === 'collection' && selectedBox) {
      onLog({ boxId: selectedBox.id, qty, date, notes, brand: selectedBox.brand, name: selectedBox.name, boxNum: selectedBox.boxNum, source: 'collection' });
      onClose();
    } else if (source === 'external' && externalBrand && externalName) {
      onLog({ qty, date, notes, brand: externalBrand, name: externalName, boxNum: 'EXT', source: 'external' });
      onClose();
    }
  };
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose} style={{ background: 'rgba(0,0,0,0.9)' }}>
      <div className="w-full max-w-sm rounded-2xl max-h-[85vh] overflow-y-auto" style={{ background: '#1a120b', border: '1px solid #6B1E1E', scrollbarWidth: 'none', msOverflowStyle: 'none' }} onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 z-10 p-4 flex justify-between items-center" style={{ background: '#1a120b', borderBottom: '1px solid #6B1E1E' }}>
          <h3 className="text-lg font-bold" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Log Smoke</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'rgba(245,222,179,0.1)', color: '#F5DEB3' }}>×</button>
        </div>
        
        <div className="p-4 space-y-4">
          {/* Source Selection */}
          {!source && (
            <div className="space-y-3">
              <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Where is this cigar from?</label>
              <button 
                onClick={() => setSource('collection')} 
                className="w-full py-4 rounded-lg text-lg font-bold"
                style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', color: '#1a120b' }}
              >
                My Collection
              </button>
              <button 
                onClick={() => setSource('external')} 
                className="w-full py-4 rounded-lg text-lg font-semibold"
                style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.2)', color: 'rgba(245,222,179,0.6)' }}
              >
                External
              </button>
            </div>
          )}
          
          {/* Collection Flow */}
          {source === 'collection' && (
            <>
              <button onClick={() => setSource(null)} className="text-sm" style={{ color: 'rgba(245,222,179,0.5)' }}>← Back</button>
              
              <div>
                <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Date</label>
                <input type="date" value={date} onChange={e => setDate(e.target.value)} className="w-full px-3 py-2 rounded-lg text-sm" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3', WebkitAppearance: 'none', minHeight: '42px' }} />
              </div>
              
              <div>
                <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Select Cigar</label>
                <div className="max-h-60 overflow-y-auto" style={{ scrollbarWidth: 'none' }}>
                  {(() => {
                    const brands = {};
                    available.forEach(b => {
                      if (!brands[b.brand]) brands[b.brand] = [];
                      brands[b.brand].push(b);
                    });
                    return Object.entries(brands).sort(([a], [b]) => a.localeCompare(b)).map(([brand, brandBoxes]) => (
                      <div key={brand} className="mb-3">
                        <div className="text-xs font-bold tracking-wide mb-1.5 pb-1" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif', borderBottom: '1px solid rgba(245,222,179,0.15)' }}>{brand}</div>
                        <div className="space-y-1.5">
                          {brandBoxes.sort((a, b) => a.name.localeCompare(b.name) || String(a.boxNum).localeCompare(String(b.boxNum), undefined, { numeric: true })).map(b => {
                            const isSelected = selectedBox?.id === b.id;
                            const isOpen = b.remaining > 0 && b.remaining < b.perBox;
                            return (
                              <div key={b.id} onClick={() => { setSelectedBox(b); setQty(1); }} className="relative flex items-center justify-between p-2.5 rounded-lg cursor-pointer" style={{ 
                                background: isSelected ? 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' : 'rgba(245,222,179,0.08)',
                                border: `1px solid ${isSelected ? '#6B1E1E' : 'rgba(245,222,179,0.15)'}`
                              }}>
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm font-medium" style={{ color: isSelected ? '#1a120b' : 'rgba(245,222,179,0.9)' }}>{b.name}</div>
                                  <div className="text-xs" style={{ color: isSelected ? 'rgba(26,18,11,0.5)' : 'rgba(245,222,179,0.4)' }}>Box of {b.perBox} • {b.location}</div>
                                </div>
                                {/* Box indicator */}
                                <div className="flex-shrink-0 flex items-end gap-0.5 ml-2">
                                  <div className="rounded-sm flex items-center justify-center" style={{
                                    width: '24px',
                                    height: '18px',
                                    background: isSelected ? '#6B1E1E' : '#6B1E1E',
                                    border: isOpen ? '2px solid #F5DEB3' : 'none',
                                  }}>
                                    <span className="text-xs font-bold" style={{ color: '#fff', fontSize: 10 }}>{b.boxNum}</span>
                                  </div>
                                </div>
                                {isOpen && (
                                  <div className="absolute -top-1 -right-1 w-5 h-5 rounded-full flex items-center justify-center font-bold shadow-lg" 
                                    style={{ background: '#6B1E1E', color: '#fff', fontSize: 10 }}>{b.remaining}</div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ));
                  })()}
                </div>
              </div>
              
              {selectedBox && (
                <>
                  <div>
                    <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Quantity</label>
                    <div className="flex items-center gap-4">
                      <button onClick={() => setQty(Math.max(1, qty - 1))} className="w-10 h-10 rounded-lg text-lg font-bold" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }}>-</button>
                      <span className="text-2xl font-bold" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif', minWidth: 40, textAlign: 'center' }}>{qty}</span>
                      <button onClick={() => setQty(Math.min(selectedBox.remaining, qty + 1))} className="w-10 h-10 rounded-lg text-lg font-bold" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }}>+</button>
                    </div>
                  </div>
                  
                  <div>
                    <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Notes (optional)</label>
                    <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Tasting notes, occasion..." className="w-full px-3 py-2 rounded-lg text-sm resize-none" rows={2} style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }} />
                  </div>
                  
                  <button onClick={handleSubmit} className="w-full py-3 rounded-lg font-bold" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', color: '#1a120b' }}>
                    Log {qty} Cigar{qty > 1 ? 's' : ''}
                  </button>
                </>
              )}
            </>
          )}
          
          {/* External Flow */}
          {source === 'external' && (
            <>
              <button onClick={() => setSource(null)} className="text-sm" style={{ color: 'rgba(245,222,179,0.5)' }}>← Back</button>
              
              <div>
                <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Date</label>
                <input type="date" value={date} onChange={e => setDate(e.target.value)} className="w-full px-3 py-2 rounded-lg text-sm" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3', WebkitAppearance: 'none', minHeight: '42px' }} />
              </div>
              
              <div>
                <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Brand</label>
                <input type="text" value={externalBrand} onChange={e => setExternalBrand(e.target.value)} placeholder="e.g. Cohiba" className="w-full px-3 py-2 rounded-lg text-sm" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }} />
              </div>
              
              <div>
                <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Cigar Name</label>
                <input type="text" value={externalName} onChange={e => setExternalName(e.target.value)} placeholder="e.g. Siglo VI" className="w-full px-3 py-2 rounded-lg text-sm" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }} />
              </div>
              
              <div>
                <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Quantity</label>
                <div className="flex items-center gap-4">
                  <button onClick={() => setQty(Math.max(1, qty - 1))} className="w-10 h-10 rounded-lg text-lg font-bold" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }}>-</button>
                  <span className="text-2xl font-bold" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif', minWidth: 40, textAlign: 'center' }}>{qty}</span>
                  <button onClick={() => setQty(qty + 1)} className="w-10 h-10 rounded-lg text-lg font-bold" style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }}>+</button>
                </div>
              </div>
              
              <div>
                <label className="text-xs block mb-2" style={{ color: 'rgba(245,222,179,0.5)' }}>Notes (optional)</label>
                <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Tasting notes, occasion..." className="w-full px-3 py-2 rounded-lg text-sm resize-none" rows={2} style={{ background: 'rgba(245,222,179,0.08)', border: '1px solid rgba(245,222,179,0.15)', color: '#F5DEB3' }} />
              </div>
              
              {externalBrand && externalName && (
                <button onClick={handleSubmit} className="w-full py-3 rounded-lg font-bold" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)', color: '#1a120b' }}>
                  Log {qty} Cigar{qty > 1 ? 's' : ''}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

// Complete Habanos S.A. Cuban Cigar Catalog - Ring Gauge and Length (in inches)
const habanosCatalog = {

  // ==================== BOLIVAR ====================
  'Bolivar': {
    'Belicosos Finos': { ring: 52, length: '5 1/2', notes: 'Campanas' },
    'Royal Coronas': { ring: 50, length: '4 7/8', notes: 'Robusto - 2006 Cigar of the Year' },
    'Petit Coronas': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Coronas Junior': { ring: 42, length: '4 3/8', notes: 'Minutos' },
    'Coronas Extra': { ring: 44, length: '5 5/8', notes: 'Coronas Extra - Discontinued 2012' },
    'Coronas Gigantes': { ring: 47, length: '7', notes: 'Julieta No.2 / Churchill' },
    'Gold Medal': { ring: 42, length: '6 1/2', notes: 'Cervantes - Discontinued 2011' },
    'New Gold Medal': { ring: 48, length: '6 1/2', notes: 'Corona Extra - LCDH Exclusive' },
    'Libertador': { ring: 54, length: '6 1/2', notes: 'Sublimes - LCDH (originally RE France 2007)' },
  },

  // ==================== COHIBA ====================
  'Cohiba': {
    'Siglo I': { ring: 40, length: '4', notes: 'Perlas / Tres Petit Corona' },
    'Siglo II': { ring: 42, length: '5 1/8', notes: 'Mareva / Petit Corona' },
    'Siglo III': { ring: 42, length: '6 1/8', notes: 'Corona Grande' },
    'Siglo IV': { ring: 46, length: '5 5/8', notes: 'Corona Gorda' },
    'Siglo V': { ring: 43, length: '6 3/4', notes: 'Dalia / Lonsdale (8-9-8)' },
    'Siglo VI': { ring: 52, length: '5 7/8', notes: 'Cañonazo / Robusto Extra' },
    'Medio Siglo': { ring: 52, length: '4', notes: 'Medio Robusto - Released 2016' },
    'Lanceros': { ring: 38, length: '7 1/2', notes: 'Laguito No.1 (original Cohiba 1966)' },
    'Coronas Especiales': { ring: 38, length: '6', notes: 'Laguito No.2' },
    'Panetelas': { ring: 26, length: '4 1/2', notes: 'Laguito No.3' },
    'Esplendidos': { ring: 47, length: '7', notes: 'Julieta No.2 / Churchill' },
    'Robustos': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'Exquisitos': { ring: 36, length: '5', notes: 'Seoane (some sources: 33 ring)' },
    'Piramides Extra': { ring: 54, length: '6 1/4', notes: 'Pirámides Extra - Released 2012' },
    'Ambar': { ring: 53, length: '5 1/4', notes: 'Placeres - Released 2021' },
    'Maduro 5 Secretos': { ring: 40, length: '4 1/3', notes: 'Petit Corona' },
    'Maduro 5 Magicos': { ring: 52, length: '4 1/2', notes: 'Petit Robusto' },
    'Maduro 5 Genios': { ring: 52, length: '5 1/2', notes: 'Genios / Robusto Extra' },
    'Behike 52': { ring: 52, length: '4 3/4', notes: 'Laguito No.4' },
    'Behike 54': { ring: 54, length: '5 3/4', notes: 'Laguito No.5' },
    'Behike 56': { ring: 56, length: '6 1/2', notes: 'Laguito No.6' },
    'Behike 58': { ring: 58, length: '7', notes: 'Laguito No.7 - Released 2025' },
    'Talisman': { ring: 54, length: '6 1/8', notes: 'Cañonazo Doble - Edición Limitada 2017' },
    'Vistosos': { ring: 53, length: '5 3/4', notes: 'Dinoras - Travel Retail Exclusive 2024' },
    'Ideales': { ring: 56, length: '6 7/8', notes: 'Modernas - Colección Habanos 2021' },
  },

  // ==================== CUABA ====================
  'Cuaba': {
    'Divinos': { ring: 43, length: '4', notes: 'Petit Perfecto' },
    'Tradicionales': { ring: 42, length: '4 7/8', notes: 'Perfecto' },
    'Generosos': { ring: 42, length: '5 1/8', notes: 'Double Figurado' },
    'Exclusivos': { ring: 46, length: '5 3/4', notes: 'Double Figurado' },
    'Salomones': { ring: 57, length: '7 1/4', notes: 'Double Figurado' },
  },

  // ==================== DIPLOMATICOS ====================
  'Diplomaticos': {
    'No. 2': { ring: 52, length: '6 1/8', notes: 'Pirámides' },
    'No. 4': { ring: 42, length: '5 1/8', notes: 'Mareva / Petit Corona' },
    'No. 5': { ring: 40, length: '4', notes: 'Perla' },
    'No. 6': { ring: 34, length: '5 7/8', notes: 'Eminentes' },
    'No. 7': { ring: 38, length: '6', notes: 'Laguito No.2' },
    'Cancilleres': { ring: 52, length: '5 5/8', notes: 'Sublime - 2025 release' },
  },

  // ==================== EL REY DEL MUNDO ====================
  'El Rey del Mundo': {
    'Choix Supreme': { ring: 48, length: '5', notes: 'Hermoso No.4' },
    'Demi Tasse': { ring: 30, length: '3 7/8', notes: 'Entreacto' },
    'Gran Corona': { ring: 42, length: '5 1/2', notes: 'Corona Grande' },
    'Lunch Club': { ring: 42, length: '4 3/8', notes: 'Minutos' },
    'Petit Corona': { ring: 42, length: '5 1/8', notes: 'Mareva' },
  },

  // ==================== FONSECA ====================
  'Fonseca': {
    'Cosacos': { ring: 42, length: '5 3/8', notes: 'Cosaco' },
    'Delicias': { ring: 25, length: '4 7/8', notes: 'Seoane Delgado' },
    'No. 1': { ring: 44, length: '6 1/2', notes: 'Cervantes' },
    'Cadetes': { ring: 36, length: '4 1/2', notes: 'Cadete' },
    'KDT': { ring: 36, length: '4 1/2', notes: 'Cadete' },
  },

  // ==================== H. UPMANN ====================
  'H. Upmann': {
    'No. 2': { ring: 52, length: '6 1/8', notes: 'Pirámides' },
    'Magnum 46': { ring: 46, length: '5 5/8', notes: 'Corona Gorda' },
    'Magnum 48': { ring: 48, length: '5 1/4', notes: 'Hermoso No.4 Extra - Edición Limitada 2009' },
    'Magnum 50': { ring: 50, length: '6 1/4', notes: 'Doble Robusto' },
    'Magnum 52': { ring: 52, length: '5 1/4', notes: 'Venerables' },
    'Magnum 54': { ring: 54, length: '4 3/4', notes: 'Petit Edmundo Extra' },
    'Magnum 56': { ring: 56, length: '6', notes: 'Cañonazo Extra' },
    'Half Corona': { ring: 44, length: '3 1/2', notes: 'Minutos' },
    'Petit Upmann': { ring: 36, length: '4 1/2', notes: 'Cadete' },
    'Connoisseur No. 1': { ring: 48, length: '5', notes: 'Hermoso No.4' },
    'Connoisseur A': { ring: 52, length: '5 1/2', notes: 'Genios - LCDH exclusive' },
    'Connoisseur B': { ring: 54, length: '5', notes: 'Edmundo Extra' },
    'Connoisseur No. 2': { ring: 52, length: '5 3/8', notes: 'Robusto Extra - LCDH exclusive' },
    'Sir Winston': { ring: 47, length: '7', notes: 'Julieta No.2 / Churchill' },
    'Royal Robusto': { ring: 52, length: '5 3/8', notes: 'Robusto Extra' },
    'Regalias': { ring: 42, length: '4 1/2', notes: 'Mareva Corta' },
    'Majestic': { ring: 42, length: '5 7/8', notes: 'Corona Grande' },
    'Coronas Major': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Coronas Minor': { ring: 40, length: '4 5/8', notes: 'Petit Corona' },
    'Epicures': { ring: 50, length: '5', notes: 'Hermoso No.4' },
  },

  // ==================== HOYO DE MONTERREY ====================
  'Hoyo de Monterrey': {
    'Epicure No. 1': { ring: 46, length: '5 5/8', notes: 'Corona Gorda' },
    'Epicure No. 2': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'Epicure Especial': { ring: 50, length: '5 5/8', notes: 'Gordito / Double Robusto' },
    'Double Corona': { ring: 49, length: '7 5/8', notes: 'Prominentes' },
    'Le Hoyo de Rio Seco': { ring: 56, length: '5 1/2', notes: 'Aromosos - LCDH exclusive 2018' },
    'Le Hoyo de San Juan': { ring: 54, length: '5 7/8', notes: 'Geniales - LCDH exclusive 2014' },
    'Le Hoyo de San Luis': { ring: 54, length: '6 1/4', notes: 'Geniales Extra - LCDH exclusive' },
    'Petit Robustos': { ring: 50, length: '4', notes: 'Petit Robusto' },
    'Coronas': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
    'Palmas Extra': { ring: 35, length: '5 5/8', notes: 'Palma' },
    'Du Depute': { ring: 38, length: '4 3/8', notes: 'Small Panetela' },
    'Du Maire': { ring: 42, length: '5 7/8', notes: 'Corona' },
    'Du Prince': { ring: 40, length: '5', notes: 'Crema' },
    'Du Roi': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Destinos': { ring: 52, length: '5 5/8', notes: 'Cañonazo - Edición Limitada' },
    'Short Hoyo Piramides': { ring: 46, length: '5', notes: 'Petit Pirámides - LCDH exclusive' },
  },

  // ==================== JOSE L. PIEDRA ====================
  'Jose L. Piedra': {
    'Brevas': { ring: 38, length: '5', notes: 'Small Panetela' },
    'Cazadores': { ring: 43, length: '6 1/8', notes: 'Cazador' },
    'Conservas': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
    'Cremas': { ring: 40, length: '5', notes: 'Crema' },
    'Petit Caballeros': { ring: 40, length: '4 7/8', notes: 'Petit Crema' },
    'Petit Cazadores': { ring: 40, length: '4 3/8', notes: 'Perla Fina' },
    'Petit Cetros': { ring: 26, length: '4 1/2', notes: 'Laguito No.3' },
  },

  // ==================== JUAN LOPEZ ====================
  'Juan Lopez': {
    'Seleccion No. 1': { ring: 46, length: '6 1/2', notes: 'Dalias' },
    'Seleccion No. 2': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'Petit Coronas': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Coronas': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
  },

  // ==================== LA FLOR DE CANO ====================
  'La Flor de Cano': {
    'Petit Coronas': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Selectos': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'Short Churchills': { ring: 50, length: '4 7/8', notes: 'Robusto' },
  },

  // ==================== LA GLORIA CUBANA ====================
  'La Gloria Cubana': {
    'Medaille d\'Or No. 1': { ring: 36, length: '7 1/4', notes: 'Delicado Extra' },
    'Medaille d\'Or No. 2': { ring: 43, length: '6 7/8', notes: 'Gran Corona' },
    'Medaille d\'Or No. 3': { ring: 28, length: '7', notes: 'Gran Panetela' },
    'Medaille d\'Or No. 4': { ring: 32, length: '6', notes: 'Panetela Largo' },
    'Glorias': { ring: 53, length: '5 1/4', notes: 'Placeres' },
    'Orgullosos': { ring: 56, length: '5 5/8', notes: 'Robusto Gordo - LCDH exclusive' },
    '35 Aniversario': { ring: 52, length: '4 7/8', notes: 'Robusto - Commemorative' },
  },

  // ==================== MONTECRISTO ====================
  'Montecristo': {
    'No. 1': { ring: 42, length: '6 1/2', notes: 'Cervantes / Lonsdale' },
    'No. 2': { ring: 52, length: '6 1/8', notes: 'Pirámides / Torpedo' },
    'No. 3': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
    'No. 4': { ring: 42, length: '5 1/8', notes: 'Mareva / Petit Corona' },
    'No. 5': { ring: 40, length: '4', notes: 'Perlas' },
    'Petit No. 2': { ring: 52, length: '4 7/8', notes: 'Pirámides Corto' },
    'Especial': { ring: 38, length: '7 1/2', notes: 'Laguito No.1' },
    'Especial No. 2': { ring: 38, length: '6', notes: 'Laguito No.2' },
    'Open Master': { ring: 50, length: '5 1/4', notes: 'Robusto Extra' },
    'Open Eagle': { ring: 54, length: '5 7/8', notes: 'Duke' },
    'Open Regata': { ring: 46, length: '5 3/8', notes: 'Corona Gorda Extra' },
    'Open Junior': { ring: 40, length: '4', notes: 'Perla' },
    'Edmundo': { ring: 52, length: '5 3/8', notes: 'Edmundo' },
    'Double Edmundo': { ring: 50, length: '6 1/8', notes: 'Dobles' },
    'Petit Edmundo': { ring: 52, length: '4 3/8', notes: 'Petit Edmundo' },
    'Media Corona': { ring: 44, length: '3 1/2', notes: 'Half Corona' },
    'Supremos': { ring: 55, length: '5 1/8', notes: 'Montesco - Edición Limitada 2019' },
    'Grand Edmundo': { ring: 52, length: '6 1/4', notes: 'Edmundo Extra - Edición Limitada' },
    'Leyendas': { ring: 53, length: '6 1/8', notes: 'Colección Habanos' },
    'Brillantes': { ring: 53, length: '5', notes: 'Venerables - Year of the Dragon 2024' },
    'Linea 1935 Dumas': { ring: 49, length: '5 1/8', notes: 'Prominente Corto' },
    'Linea 1935 Maltes': { ring: 53, length: '6', notes: 'Sobresalientes' },
    'Linea 1935 Leyenda': { ring: 55, length: '6 1/2', notes: 'Maravillas No.2' },
    'Elba': { ring: 50, length: '5', notes: 'Hermoso No.4 - LCDH exclusive' },
  },

  // ==================== PARTAGAS ====================
  'Partagas': {
    'Serie D No. 4': { ring: 50, length: '4 7/8', notes: 'Robusto - most popular Cuban' },
    'Serie D No. 5': { ring: 50, length: '4 3/8', notes: 'Petit Robusto' },
    'Serie D No. 6': { ring: 50, length: '3 1/2', notes: 'Petit Robusto' },
    'Serie P No. 2': { ring: 52, length: '6 1/8', notes: 'Pirámides' },
    'Serie E No. 2': { ring: 54, length: '5 1/2', notes: 'Duke' },
    'Lusitanias': { ring: 49, length: '7 5/8', notes: 'Prominentes / Double Corona' },
    'Shorts': { ring: 42, length: '4 3/8', notes: 'Minutos' },
    'Coronas Senior': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Mille Fleurs': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    '8-9-8': { ring: 43, length: '6 7/8', notes: 'Dalias' },
    'Presidentes': { ring: 47, length: '6 1/4', notes: 'Prominentes' },
    'Aristocrats': { ring: 43, length: '5 1/8', notes: 'Cazador' },
    'Culebras': { ring: 39, length: '5 3/4', notes: 'Culebra (3 braided)' },
    'Habaneros': { ring: 47, length: '5 1/8', notes: 'Petit Cetros' },
    'Petit Coronas Especiales': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Super Partagas': { ring: 40, length: '5 5/8', notes: 'Corona Grande' },
    'Linea Maestra Maestros': { ring: 47, length: '6 1/4', notes: 'Gran Corona' },
  },

  // ==================== POR LARRANAGA ====================
  'Por Larranaga': {
    'Petit Coronas': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Panetelas': { ring: 33, length: '4 1/2', notes: 'Panetela Corta' },
    'Montecarlo': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Picadores': { ring: 38, length: '4 3/8', notes: 'Short Panetela' },
  },

  // ==================== PUNCH ====================
  'Punch': {
    'Punch Punch': { ring: 46, length: '5 5/8', notes: 'Corona Gorda' },
    'Double Coronas': { ring: 49, length: '7 5/8', notes: 'Prominentes' },
    'Petit Coronas del Punch': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Royal Coronations': { ring: 44, length: '5 1/2', notes: 'Coronation' },
    'Coronations': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Super Selection No. 1': { ring: 46, length: '5 1/2', notes: 'Corona Extra' },
    'Super Selection No. 2': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
    'Short de Punch': { ring: 42, length: '4 3/8', notes: 'Minutos' },
    'Princesas': { ring: 30, length: '4 7/8', notes: 'Small Panetela' },
  },

  // ==================== QUAI D'ORSAY ====================
  'Quai d\'Orsay': {
    'No. 50': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'No. 54': { ring: 54, length: '6 1/8', notes: 'Sublime' },
    'Senadores': { ring: 48, length: '5', notes: '' },
    'Coronas Claro': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
    'Especial d\'Orsay': { ring: 54, length: '7 3/4', notes: 'Gran Prominentes' },
  },

  // ==================== QUINTERO ====================
  'Quintero': {
    'Favoritos': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Nacionales': { ring: 40, length: '5 5/8', notes: 'Corona Grande' },
    'Petit Quinteros': { ring: 40, length: '4 3/8', notes: 'Perla Fina' },
    'Panetelas': { ring: 37, length: '5', notes: 'Panetela Corta' },
    'Brevas': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
    'Londres Extra': { ring: 40, length: '4 7/8', notes: 'Mareva Chica' },
    'Tubulares': { ring: 42, length: '6', notes: 'Corona Tubos' },
  },

  // ==================== RAFAEL GONZALEZ ====================
  'Rafael Gonzalez': {
    'Petit Coronas': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Panetelas Extra': { ring: 37, length: '5', notes: 'Panetela Corta' },
    'Perlas': { ring: 40, length: '4', notes: 'Perla' },
    'Coronas Extra': { ring: 46, length: '5 5/8', notes: 'Corona Gorda' },
    'Lonsdales': { ring: 42, length: '6 1/2', notes: 'Cervantes' },
  },

  // ==================== RAMON ALLONES ====================
  'Ramon Allones': {
    'Specially Selected': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'Small Club Coronas': { ring: 42, length: '4 3/8', notes: 'Minutos' },
    'Allones Extra': { ring: 44, length: '5 1/2', notes: 'Coronation' },
    'Gigantes': { ring: 49, length: '7 5/8', notes: 'Prominentes' },
    'Club Allones': { ring: 53, length: '5', notes: 'Dinoras - LCDH exclusive' },
    'No. 2': { ring: 52, length: '5 1/2', notes: 'Campanas - Edición Limitada 2019' },
    'Superiores': { ring: 46, length: '5 5/8', notes: 'Corona Gorda - LCDH exclusive 2010' },
    'Absolutos': { ring: 54, length: '5 5/8', notes: 'Duke - Edición Limitada' },
  },

  // ==================== ROMEO Y JULIETA ====================
  'Romeo y Julieta': {
    'Churchills': { ring: 47, length: '7', notes: 'Julieta No.2' },
    'Wide Churchills': { ring: 55, length: '5 1/8', notes: 'Montesco' },
    'Short Churchills': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'Petit Churchills': { ring: 50, length: '4', notes: 'Petit Robusto' },
    'Coronitas en Cedro': { ring: 40, length: '5', notes: 'Coronita' },
    'Petit Royales': { ring: 47, length: '4 7/8', notes: 'Petit Robusto' },
    'No. 1': { ring: 40, length: '5 5/8', notes: 'Mareva Gorda' },
    'No. 2': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'No. 3': { ring: 40, length: '4 5/8', notes: 'Petit Corona' },
    'Belicosos': { ring: 52, length: '5 1/2', notes: 'Campana' },
    'Cedros de Luxe No. 1': { ring: 42, length: '6 1/2', notes: 'Cervantes (cedar wrapped)' },
    'Cedros de Luxe No. 2': { ring: 42, length: '5 5/8', notes: 'Corona Grande (cedar)' },
    'Cedros de Luxe No. 3': { ring: 42, length: '5 1/8', notes: 'Mareva (cedar)' },
    'Cazadores': { ring: 44, length: '6 3/8', notes: 'Cazador' },
    'Exhibicion No. 4': { ring: 48, length: '5', notes: 'Hermoso No.4' },
    'Mille Fleurs': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Romeo No. 1': { ring: 40, length: '5 5/8', notes: 'Crema' },
    'Romeo No. 2': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Romeo No. 3': { ring: 40, length: '4 5/8', notes: 'Petit Corona' },
    'Sport Largos': { ring: 35, length: '6 1/4', notes: 'Panetela Larga' },
    'Cupidos': { ring: 50, length: '5 1/8', notes: 'Campana Corta' },
    'Amantes': { ring: 53, length: '5', notes: 'Dinoras - LCDH exclusive' },
  },

  // ==================== SAINT LUIS REY ====================
  'Saint Luis Rey': {
    'Serie A': { ring: 54, length: '5 5/8', notes: 'Duke' },
    'Regios': { ring: 48, length: '5', notes: 'Hermoso No.4' },
    'Churchill': { ring: 47, length: '7', notes: 'Julieta No.2' },
    'Petit Coronas': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Marquez': { ring: 42, length: '5 1/8', notes: 'Mareva' },
  },

  // ==================== SAN CRISTOBAL DE LA HABANA ====================
  'San Cristobal de la Habana': {
    'La Fuerza': { ring: 50, length: '4 7/8', notes: 'Robusto' },
    'El Morro': { ring: 52, length: '5 1/2', notes: 'Campana' },
    'La Punta': { ring: 52, length: '5 7/8', notes: 'Cañonazo' },
    'El Principe': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Oficios': { ring: 52, length: '5 1/2', notes: 'Genios' },
    'Mercaderes': { ring: 48, length: '6 5/8', notes: 'Hermoso No.1 - LCDH (discontinued)' },
    'Muralla': { ring: 54, length: '7 1/8', notes: 'Rudolfo - LCDH (discontinued)' },
    'Prado': { ring: 50, length: '5', notes: 'Petit Pirámides - LCDH exclusive 2019' },
    'O\'Reilly': { ring: 40, length: '4 3/8', notes: 'Minutos' },
    '20 Aniversario': { ring: 52, length: '6 3/8', notes: 'Capuleto / Double Robusto - LCDH 2020' },
    'Reinas': { ring: 55, length: '6 7/8', notes: 'Maravillas No.5 - Colección Habanos 2024' },
  },

  // ==================== SANCHO PANZA ====================
  'Sancho Panza': {
    'Belicosos': { ring: 52, length: '5 1/2', notes: 'Campana' },
    'Molinos': { ring: 42, length: '6 1/2', notes: 'Cervantes' },
    'Non Plus': { ring: 42, length: '5 1/8', notes: 'Mareva' },
    'Sanchos': { ring: 47, length: '9 1/4', notes: 'Gran Corona' },
    'Bachilleres': { ring: 40, length: '4 5/8', notes: 'Petit Corona' },
    'Coronas Gigantes': { ring: 42, length: '7', notes: 'Lonsdale Grande' },
  },

  // ==================== TRINIDAD ====================
  'Trinidad': {
    'Reyes': { ring: 40, length: '4 3/8', notes: 'Minutos' },
    'Coloniales': { ring: 44, length: '5 1/2', notes: 'Coronation' },
    'Robusto Extra': { ring: 50, length: '6 1/8', notes: 'Dobles' },
    'Vigia': { ring: 54, length: '4 3/8', notes: 'Medio Robusto' },
    'Fundadores': { ring: 40, length: '7 1/2', notes: 'Laguito No.1' },
    'Topes': { ring: 56, length: '4 7/8', notes: 'Topes - Edición Limitada 2016, now regular production' },
    'Media Luna': { ring: 50, length: '4 1/2', notes: 'Marinas' },
    'Esmeralda': { ring: 53, length: '5 3/4', notes: 'Dinoras' },
    'La Trova': { ring: 54, length: '6 1/2', notes: 'Cañonazo Especial - LCDH exclusive 2017' },
    'Cabildos': { ring: 54, length: '4 3/8', notes: 'Medio Robusto' },
  },

  // ==================== VEGAS ROBAINA ====================
  'Vegas Robaina': {
    'Clasicos': { ring: 42, length: '6 1/2', notes: 'Cervantes / Lonsdale' },
    'Don Alejandro': { ring: 49, length: '7 5/8', notes: 'Prominentes / Double Corona' },
    'Famosos': { ring: 48, length: '5', notes: 'Hermoso No.4 / Corona Extra' },
    'Familiar': { ring: 42, length: '5 5/8', notes: 'Corona Grande' },
    'Unicos': { ring: 52, length: '6 1/8', notes: 'Pirámides / Torpedo' },
  },

  // ==================== VEGUEROS ====================
  'Vegueros': {
    'Tapados': { ring: 46, length: '6', notes: 'Gran Corona' },
    'Especiales No. 1': { ring: 38, length: '7 1/2', notes: 'Laguito No.1 (discontinued)' },
    'Especiales No. 2': { ring: 38, length: '6', notes: 'Laguito No.2 (discontinued)' },
    'Entretiempos': { ring: 52, length: '4 3/8', notes: 'Petit Edmundo' },
    'Mananitas': { ring: 46, length: '4', notes: 'Petit' },
    'Centrofinos': { ring: 44, length: '5 5/8', notes: 'Corona Gorda' },
    'Seoane': { ring: 33, length: '5', notes: 'Small Panetela (discontinued)' },
  },

};

// Add Box Modal
const AddBoxModal = ({ boxes, onClose, onAdd, highestBoxNum }) => {
  const [brand, setBrand] = useState('');
  const [name, setName] = useState('');
  const [boxNum, setBoxNum] = useState('');
  const [perBox, setPerBox] = useState('');
  const [price, setPrice] = useState('');
  const [priceCurrency, setPriceCurrency] = useState('USD');
  const [datePurchased, setDatePurchased] = useState(new Date().toISOString().split('T')[0]);
  const [location, setLocation] = useState('Cayman');
  const [status, setStatus] = useState('Ageing');
  const [received, setReceived] = useState(false);
  const [code, setCode] = useState('');
  const [dateOfBox, setDateOfBox] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [customBrand, setCustomBrand] = useState('');
  const [customName, setCustomName] = useState('');
  const [ringGauge, setRingGauge] = useState('');
  const [length, setLength] = useState('');
  const [notes, setNotes] = useState('');
  
  // Calculate suggested box number from Settings
  const suggestedBoxNum = useMemo(() => {
    const nums = boxes.map(b => {
      const match = b.boxNum.match(/^(\d+)/);
      return match ? parseInt(match[1]) : 0;
    });
    const maxInSheet = Math.max(...nums, 0);
    return String(Math.max(maxInSheet, highestBoxNum || 0) + 1);
  }, [boxes, highestBoxNum]);
  
  // Set initial box number
  useEffect(() => {
    setBoxNum(suggestedBoxNum);
  }, [suggestedBoxNum]);
  
  // Get all Habanos brands (sorted alphabetically)
  const allBrands = useMemo(() => {
    return Object.keys(habanosCatalog).sort();
  }, []);
  
  // Get cigar names for selected brand from catalog and existing collection
  const availableNames = useMemo(() => {
    if (!brand || brand === '__custom__') return [];
    const catalogData = habanosCatalog[brand] || {};
    const catalogNames = Object.keys(catalogData);
    const collectionNames = boxes.filter(b => b.brand === brand).map(b => b.name);
    const allNames = [...new Set([...catalogNames, ...collectionNames])];
    return allNames.sort();
  }, [boxes, brand]);
  
  // Auto-populate ring gauge, length, and notes when vitola is selected
  useEffect(() => {
    if (brand && brand !== '__custom__' && name && name !== '__custom__') {
      const catalogData = habanosCatalog[brand]?.[name];
      if (catalogData) {
        setRingGauge(String(catalogData.ring || ''));
        setLength(catalogData.length || '');
        setNotes(catalogData.notes || '');
      } else {
        // Cigar not in catalog (maybe from collection), clear fields
        setRingGauge('');
        setLength('');
        setNotes('');
      }
    } else {
      // Custom brand/name, clear fields
      setRingGauge('');
      setLength('');
      setNotes('');
    }
  }, [brand, name]);
  
  const handleSubmit = () => {
    const finalBrand = brand === '__custom__' ? customBrand : brand;
    const finalName = (brand === '__custom__' || name === '__custom__') ? customName : name;
    
    if (!finalBrand || !finalName || !perBox || !price) return;
    
    const newBoxes = [];
    const baseNum = boxNum;
    
    for (let i = 0; i < quantity; i++) {
      const newId = Math.max(...boxes.map(b => b.id), 0) + 1 + i;
      const newBoxNum = quantity > 1 ? `${baseNum}.${i + 1}` : baseNum;
      
      newBoxes.push({
  id: newId,
  boxNum: newBoxNum,
  brand: finalBrand,
  name: finalName,
  datePurchased,
  received,
  perBox: parseInt(perBox),
  price: parseFloat(price),
  currency: priceCurrency,
  status,
  dateOfBox: dateOfBox || '',
  code: code || '',
  location,
  consumed: 0,
  remaining: parseInt(perBox),
  ringGauge: ringGauge,
  length: length,
  vitola: notes,
  boxNotes: '',
});
    }
    
    onAdd(newBoxes);
    onClose();
  };
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-8" onClick={onClose} style={{ background: 'rgba(0,0,0,0.9)' }}>
      <div className="w-full max-w-md rounded-2xl max-h-[90vh] overflow-y-auto" style={{ background: '#1a1a1a', border: '1px solid #333', scrollbarWidth: 'none', msOverflowStyle: 'none' }} onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 z-10 p-4 flex justify-between items-center" style={{ background: '#1a1a1a', borderBottom: '1px solid #333' }}>
          <h3 className="text-lg font-semibold" style={{ color: '#F5DEB3' }}>Add New Box</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: '#333', color: '#888' }}>×</button>
        </div>
        
        <div className="p-4 space-y-4">
          {/* Date Purchased and Price */}
          <div className="grid grid-cols-2 gap-3">
            <div style={{ overflow: 'hidden' }}>
              <label className="text-xs text-gray-500 block mb-2">Date Purchased</label>
              <input type="date" value={datePurchased} onChange={e => setDatePurchased(e.target.value)} className="w-full px-2 py-2 rounded-lg" style={{ background: '#252525', border: '1px solid #333', color: '#fff', fontSize: '14px', WebkitAppearance: 'none', minHeight: '42px' }} />
            </div>
            <div className="min-w-0">
              <label className="text-xs text-gray-500 block mb-2">Price *</label>
              <div className="flex gap-1">
                <select 
                  value={priceCurrency} 
                  onChange={e => setPriceCurrency(e.target.value)}
                  className="px-2 py-2 rounded-lg text-sm flex-shrink-0"
                  style={{ background: '#252525', border: '1px solid #333', color: '#fff', width: '70px' }}
                >
                  {CURRENCIES.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <input type="number" value={price} onChange={e => setPrice(e.target.value)} placeholder="e.g. 2500" className="flex-1 min-w-0 px-2 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} />
              </div>
            </div>
          </div>
          
          {/* Brand */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Brand *</label>
            <select value={brand} onChange={e => { setBrand(e.target.value); setName(''); setCustomBrand(''); setCustomName(''); }} className="w-full px-3 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }}>
              <option value="">Select brand...</option>
              {allBrands.map(b => <option key={b} value={b}>{b}</option>)}
              <option value="__custom__">— Custom Brand —</option>
            </select>
            {brand === '__custom__' && (
              <input 
                type="text" 
                value={customBrand} 
                onChange={e => setCustomBrand(e.target.value)} 
                placeholder="Enter custom brand name..." 
                className="w-full px-3 py-2 rounded-lg text-base mt-2" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            )}
          </div>
          
          {/* Cigar Name */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Cigar Name *</label>
            {brand === '__custom__' ? (
              <input 
                type="text" 
                value={customName} 
                onChange={e => setCustomName(e.target.value)} 
                placeholder="Enter cigar name..." 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            ) : (
              <>
                <select value={name} onChange={e => { setName(e.target.value); setCustomName(''); }} className="w-full px-3 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} disabled={!brand}>
                  <option value="">{brand ? 'Select cigar...' : 'Select brand first'}</option>
                  {availableNames.map(n => <option key={n} value={n}>{n}</option>)}
                  {brand && <option value="__custom__">— Custom Cigar —</option>}
                </select>
                {name === '__custom__' && (
                  <input 
                    type="text" 
                    value={customName} 
                    onChange={e => setCustomName(e.target.value)} 
                    placeholder="Enter custom cigar name..." 
                    className="w-full px-3 py-2 rounded-lg text-base mt-2" 
                    style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
                  />
                )}
              </>
            )}
          </div>
          
          {/* Received */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Received</label>
            <button onClick={() => setReceived(!received)} className="w-full px-3 py-2 rounded-lg text-base text-left" style={{ background: received ? '#1c3a1c' : '#252525', border: '1px solid #333', color: received ? '#99ff99' : '#888' }}>
              {received ? 'Yes' : 'No'}
            </button>
          </div>
          
          {/* Ring Gauge and Length - Auto-populated but editable */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Ring Gauge</label>
              <input 
                type="text" 
                value={ringGauge} 
                onChange={e => setRingGauge(e.target.value)} 
                placeholder="e.g. 52" 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-2">Length (inches)</label>
              <input 
                type="text" 
                value={length} 
                onChange={e => setLength(e.target.value)} 
                placeholder="e.g. 6 1/8" 
                className="w-full px-3 py-2 rounded-lg text-base" 
                style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
              />
            </div>
          </div>
          
          {/* Vitola Notes - Auto-populated but editable */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Vitola Notes</label>
            <input 
              type="text" 
              value={notes} 
              onChange={e => setNotes(e.target.value)} 
              placeholder="e.g. Robusto, LCDH exclusive" 
              className="w-full px-3 py-2 rounded-lg text-base" 
              style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} 
            />
          </div>
          
          {/* Box Number and Quantity */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Box Number *</label>
              <input type="text" value={boxNum} onChange={e => setBoxNum(e.target.value)} placeholder={suggestedBoxNum} className="w-full px-3 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-2">Quantity</label>
              <select value={quantity} onChange={e => setQuantity(parseInt(e.target.value))} className="w-full px-3 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }}>
                {[1,2,3,4,5,6,7,8,9,10].map(n => <option key={n} value={n}>{n} box{n > 1 ? 'es' : ''}</option>)}
              </select>
            </div>
          </div>
          
          {/* Cigars Per Box */}
          <div>
            <label className="text-xs text-gray-500 block mb-2">Cigars Per Box *</label>
            <input type="number" value={perBox} onChange={e => setPerBox(e.target.value)} placeholder="e.g. 25" className="w-full px-3 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }} />
          </div>
          
          {/* Factory Code and Release Date */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Factory Code</label>
              <input type="text" value={code} onChange={e => setCode(e.target.value.toUpperCase())} placeholder="e.g. GES MAR 24" autoCapitalize="characters" className="w-full px-3 py-2 rounded-lg text-base font-mono" style={{ background: '#252525', border: '1px solid #333', color: '#fff', textTransform: 'uppercase' }} />
            </div>
            <div style={{ overflow: 'hidden' }}>
              <label className="text-xs text-gray-500 block mb-2">Release Date</label>
              <input type="month" value={dateOfBox} onChange={e => setDateOfBox(e.target.value)} className="w-full px-2 py-2 rounded-lg" style={{ background: '#252525', border: '1px solid #333', color: '#fff', fontSize: '14px', WebkitAppearance: 'none', minHeight: '42px' }} />
            </div>
          </div>
          
          {/* Location and Status */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-2">Location</label>
              <select value={location} onChange={e => setLocation(e.target.value)} className="w-full px-3 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }}>
                <option value="London">London</option>
                <option value="Cayman">Cayman</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-2">Status</label>
              <select value={status} onChange={e => setStatus(e.target.value)} className="w-full px-3 py-2 rounded-lg text-base" style={{ background: '#252525', border: '1px solid #333', color: '#fff' }}>
                <option value="Ageing">Ageing</option>
                <option value="Immediate">On Rotation</option>
                <option value="Combination">Assortment</option>
              </select>
            </div>
          </div>
          
          {/* Submit Button */}
{(() => {
  const finalBrand = brand === '__custom__' ? customBrand : brand;
  const finalName = (brand === '__custom__' || name === '__custom__') ? customName : name;
  const isValid = finalBrand && finalName && perBox && price;
  return (
    <button onClick={handleSubmit} disabled={!isValid} className="w-full py-3 rounded-lg font-semibold mt-4" style={{ background: !isValid ? '#333' : '#d4af37', color: !isValid ? '#666' : '#000' }}>
      Add {quantity} Box{quantity > 1 ? 'es' : ''}
    </button>
  );
})()}
        </div>
      </div>
    </div>
  );
};

// History View
const HistoryView = ({ history, boxes, onDelete, onEdit, onBoxClick }) => {
  if (history.length === 0) {
    return (
      <div className="px-4 py-12 text-center">
        <div className="text-4xl mb-4 opacity-50">~</div>
        <p style={{ color: 'rgba(245,222,179,0.5)' }}>No smokes logged yet</p>
        <p className="text-sm mt-2" style={{ color: 'rgba(245,222,179,0.3)' }}>Use the Log Smoke button to record your sessions</p>
      </div>
    );
  }
  
  const findGroupForBox = (boxNum, brand, name) => {
    if (boxNum === 'EXT') return null;
    const key = `${brand}|${name}`;
    const groupBoxes = boxes.filter(b => `${b.brand}|${b.name}` === key);
    if (groupBoxes.length === 0) return null;
    return { brand, name, boxes: groupBoxes };
  };
  
  const CigarIcon = () => (
    <svg width="48" height="48" viewBox="0 0 24 24" style={{ transform: 'rotate(-45deg)' }}>
      <rect x="2" y="10" width="18" height="4" rx="2" fill="#8B4513"/>
      <rect x="4" y="10" width="3" height="4" fill="#6B1E1E"/>
      <rect x="20" y="10" width="2" height="4" rx="1" fill="#888"/>
      <path d="M21 9 Q22 7 21 5" stroke="#888" strokeWidth="0.8" fill="none" opacity="0.6"/>
      <path d="M22 8 Q23 6 22 4" stroke="#888" strokeWidth="0.8" fill="none" opacity="0.4"/>
    </svg>
  );

  return (
    <div className="px-4 pt-4 space-y-3">
      {history.slice().reverse().map((h, i) => {
        const actualIndex = history.length - 1 - i;
        const group = findGroupForBox(h.boxNum, h.brand, h.name);
        const cigarCount = Math.min(h.qty, 10); // Cap at 10 icons to avoid overflow
        // Find the actual box to check if it's open
        const actualBox = boxes.find(b => b.boxNum === h.boxNum);
        const isBoxOpen = actualBox && actualBox.remaining > 0 && actualBox.remaining < actualBox.perBox;
        const isBoxFull = actualBox && actualBox.remaining === actualBox.perBox;
        return (
          <div key={i} className="p-4 rounded-lg" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
            {/* Date Header with Cigar Icons */}
            <div className="flex justify-between items-center mb-3 pb-3 border-b" style={{ borderColor: '#6B1E1E' }}>
              <div className="text-xl font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{fmt.date(h.date)}</div>
              <div className="flex items-center">
                {[...Array(cigarCount)].map((_, idx) => (
                  <div key={idx} style={{ marginLeft: idx === 0 ? 0 : '-20px' }}>
                    <CigarIcon />
                  </div>
                ))}
                {h.qty > 10 && <span className="text-sm font-medium ml-1" style={{ color: '#1a120b' }}>+{h.qty - 10}</span>}
              </div>
            </div>
            
            {/* Brand */}
            <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{h.brand}</div>
            
            {/* Cigar Name */}
            <div className="text-base font-medium" style={{ color: '#1a120b' }}>{h.name}</div>
            
            {/* Box Indicator */}
            <div className="flex justify-between items-center mt-2">
              {h.boxNum === 'EXT' ? (
                <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>External</div>
              ) : (
                <button
                  onClick={() => group && onBoxClick && onBoxClick(group, h.boxNum)}
                  className="px-3 py-1.5 text-sm font-medium"
                  style={{ 
                    background: '#6B1E1E', 
                    color: '#F5DEB3', 
                    borderRadius: '4px', 
                    fontFamily: 'tt-ricordi-allegria, Georgia, serif', 
                    border: isBoxOpen ? '2px solid #1a120b' : 'none', 
                    cursor: group ? 'pointer' : 'default' 
                  }}
                >
                  Box {h.boxNum}
                </button>
              )}
              {h.notes && <div className="text-sm italic text-right" style={{ color: 'rgba(26,18,11,0.7)', maxWidth: '60%' }}>{h.notes}</div>}
            </div>
            
            {onEdit && (
              <div className="mt-3 pt-3 border-t" style={{ borderColor: '#6B1E1E' }}>
                <button
                  onClick={() => onEdit(actualIndex, h)}
                  className="w-full py-2 text-sm font-medium rounded-lg"
                  style={{ background: '#1a120b', color: '#F5DEB3' }}
                >
                  Edit
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

// Prices View
const PricesView = ({ boxes, currency, FX, fmtCurrency, fmtFromGBP }) => {
  // Get unique cigars from collection for comparison
  const collectionCigars = useMemo(() => {
    const seen = new Set();
    return boxes.filter(b => {
      const key = `${b.brand}|${b.name}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map(b => ({
      brand: b.brand,
      name: b.name,
      perBox: b.perBox,
      yourCostUSD: b.priceUSD,
    }));
  }, [boxes]);
  
  return (
    <div className="px-4 pb-8 pt-4">
      {/* Price metadata */}
      <div className="mb-6">
        <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>UK Market Prices</h2>
        <div className="rounded-lg p-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
          <div className="flex justify-between items-center">
            <div>
              <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Last Updated</div>
              <div className="text-lg font-medium" style={{ color: '#1a120b' }}>{PRICE_META.lastUpdated}</div>
            </div>
            <div className="text-right">
              <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Sources</div>
              <div className="text-base font-medium" style={{ color: '#1a120b' }}>{PRICE_META.sources.join(', ')}</div>
            </div>
          </div>
        </div>
      </div>
      
      {/* Price list by brand */}
      {Object.entries(ukMarket).map(([brand, cigars]) => (
        <div key={brand} className="mb-6">
          <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{brand}</h2>
          <div className="space-y-2">
            {Object.entries(cigars).map(([name, data]) => {
              const inCollection = collectionCigars.find(c => c.brand === brand && c.name === name);
              const marketUSD = FX.toUSD(data.gbp);
              const perCigarUSD = marketUSD / data.perBox;
              const savings = inCollection ? marketUSD - inCollection.yourCostUSD : null;
              
              return (
                <div key={name} className="rounded-lg p-3" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="text-base font-medium" style={{ color: '#1a120b' }}>{name}</div>
                      <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box of {data.perBox} • {data.source}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-xl font-medium" style={{ color: '#1a120b' }}>{fmtFromGBP(data.gbp)}</div>
                      <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>
                        {currency === 'GBP' ? fmt.usd(marketUSD) : fmt.gbp(data.gbp)}
                      </div>
                    </div>
                  </div>
                  <div className="flex justify-between items-center mt-2 pt-2 border-t" style={{ borderColor: 'rgba(26,18,11,0.15)' }}>
                    <span className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.6)' }}>
                      {fmtCurrency(perCigarUSD)} per cigar
                    </span>
                    {savings !== null && savings > 0 && (
                      <span className="text-sm font-medium" style={{ color: '#1a5a1a' }}>
                        You saved {fmtCurrency(savings)}
                      </span>
                    )}
                    {inCollection && (savings === null || savings <= 0) && (
                      <span className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>
                        In collection
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
};

// Main App
export default function CigarCollectionApp() {
  const [boxes, setBoxes] = useState([]);
  const [onwards, setOnwards] = useState([]);
  const [location, setLocation] = useState([]);
  const [selectedBrand, setSelectedBrand] = useState('All');
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [view, setView] = useState('collection');
  const [statsMode, setStatsMode] = useState('total');
  const [showLogModal, setShowLogModal] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [history, setHistory] = useState([]);
  const [editingHistory, setEditingHistory] = useState(null);
  const [showSignInPrompt, setShowSignInPrompt] = useState(false);
  const [highestBoxNum, setHighestBoxNum] = useState(0);
  const [currency, setCurrency] = useState('USD');
  const [fxRate, setFxRate] = useState(DEFAULT_FX_RATE);
  const [fxUpdated, setFxUpdated] = useState(null);
  const [fxLoading, setFxLoading] = useState(true);
  const [dataLoading, setDataLoading] = useState(true);
  const [splashDelay, setSplashDelay] = useState(true);
  const [syncStatus, setSyncStatus] = useState('idle'); // 'idle', 'syncing', 'success', 'error', 'writing'
  const [accessToken, setAccessToken] = useState(null);
  const [isSignedIn, setIsSignedIn] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [showCigarCount, setShowCigarCount] = useState(true);
  const [baseCurrency, setBaseCurrency] = useState(() => {
  const saved = localStorage.getItem('baseCurrency');
  return saved || 'USD';
});
const [fxRates, setFxRates] = useState({});
const [fxLastUpdated, setFxLastUpdated] = useState(null);
  const [collapsedBrands, setCollapsedBrands] = useState(() => {
  const saved = localStorage.getItem('collapsedBrands');
  return saved !== null ? JSON.parse(saved) : [];
});
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState([]);
  const [pullStart, setPullStart] = useState(0);
  const [pullDistance, setPullDistance] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  
  // Initialize Google Identity Services
  useEffect(() => {
    // Load the Google Identity Services library
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    document.body.appendChild(script);
    
    return () => {
      document.body.removeChild(script);
    };
  }, []);
  
  // Handle Google Sign In
  const handleGoogleSignIn = useCallback(() => {
    if (!GOOGLE_SHEETS_CONFIG.clientId) {
      alert('OAuth Client ID not configured. Please add your Client ID from Google Cloud Console.');
      return;
    }
    
    const client = window.google?.accounts?.oauth2?.initTokenClient({
      client_id: GOOGLE_SHEETS_CONFIG.clientId,
      scope: GOOGLE_SHEETS_CONFIG.scopes,
      callback: async (response) => {
        if (response.access_token) {
          setAccessToken(response.access_token);
          setIsSignedIn(true);
          googleAccessToken = response.access_token;
          // Load data after successful sign-in
          setDataLoading(true);
          setSyncStatus('syncing');
          
          try {
            const collectionRows = await fetchSheetData(response.access_token);
            if (collectionRows) {
              const boxData = collectionRows
  .filter(row => {
    const brand = row[3]?.trim();
    const name = row[4]?.trim();
    const perBox = parseInt(row[6]);
    return brand && name && perBox > 0;
  })
  .flatMap((row, idx) => expandRowToBoxesRefresh(row, idx));
setBoxes(boxData);
            }
            
            const onwardsRows = await fetchOnwardsData(response.access_token);
if (onwardsRows) {
  const onwardsData = onwardsRows
    .slice(2)
    .filter(row => {
      const brand = row[2]?.trim();
      const name = row[3]?.trim();
      return brand && name;
    })
    .map((row, idx) => rowToOnwards(row, idx));
  setOnwards(onwardsData);
}
            
            const historyRows = await fetchHistoryData(response.access_token);
            if (historyRows && historyRows.length > 1) {
              const historyData = historyRows.slice(1).map(row => ({
                date: row[0],
                boxNum: row[1],
                brand: row[2],
                name: row[3],
                qty: parseInt(row[4]) || 1,
                notes: row[5] || '',
                timestamp: Date.now()
              }));
              setHistory(historyData);
            }
            
            const storedHighest = await fetchHighestBoxNum(response.access_token);
            setHighestBoxNum(storedHighest);
            
            // Load settings from Sheets
            const sheetSettings = await fetchSettings(response.access_token);
            if (sheetSettings) {
              if (sheetSettings.showCigarCount !== undefined) {
                setShowCigarCount(sheetSettings.showCigarCount);
                localStorage.setItem('showCigarCount', JSON.stringify(sheetSettings.showCigarCount));
              }
              if (sheetSettings.baseCurrency) {
                setBaseCurrency(sheetSettings.baseCurrency);
                localStorage.setItem('baseCurrency', sheetSettings.baseCurrency);
              }
            }
            
            // Load FX rates
            const savedBaseCurrency = sheetSettings?.baseCurrency || localStorage.getItem('baseCurrency') || 'USD';
            const fxData = await fetchFxRates(savedBaseCurrency);
            if (fxData) {
              setFxRates(fxData.rates);
              setFxLastUpdated(fxData.date);
            }
            
            setSyncStatus('success');
            setView('collection'); // Always start on collection page
          } catch (error) {
            console.error('Error loading data:', error);
            setSyncStatus('error');
          } finally {
            setDataLoading(false);
          }
        }
      },
    });
    
    client?.requestAccessToken();
  }, []);
  
  // Handle Google Sign Out
  const handleGoogleSignOut = useCallback(() => {
    if (accessToken) {
      window.google?.accounts?.oauth2?.revoke(accessToken);
    }
    setAccessToken(null);
    setIsSignedIn(false);
    googleAccessToken = null;
  }, [accessToken]);
  
  // Update consumed/remaining in Google Sheets
  const updateBoxConsumed = useCallback(async (box) => {
    if (!accessToken) return false;
    
    setSyncStatus('writing');
    
    try {
      // First, fetch all data to find the row with matching box number
      const { sheetId, collectionRange } = GOOGLE_SHEETS_CONFIG;
      const fetchUrl = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${collectionRange}`;
      const fetchResponse = await fetch(fetchUrl, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
      });
      if (!fetchResponse.ok) throw new Error('Failed to fetch sheet data');
      const data = await fetchResponse.json();
      const rows = data.values || [];
      
      // Find the row index (box number is in column B, index 1)
      let rowIndex = -1;
      for (let i = 0; i < rows.length; i++) {
        if (rows[i][1] === String(box.boxNum) || rows[i][1] === box.boxNum) {
          rowIndex = i + 1; // +1 because sheets are 1-indexed
          break;
        }
      }
      
      if (rowIndex === -1) {
        throw new Error(`Box number ${box.boxNum} not found in sheet`);
      }
      
      // Update columns O (consumed) and P (remaining)
      const consumedCell = `O${rowIndex}`;
      const remainingCell = `P${rowIndex}`;
      
      await updateSheetCell(consumedCell, box.consumed, accessToken);
      await updateSheetCell(remainingCell, box.remaining, accessToken);
      setSyncStatus('success');
      return true;
    } catch (error) {
      console.error('Failed to update sheet:', error);
      setSyncStatus('error');
      return false;
    }
  }, [accessToken]);
  
  // Add new box to Google Sheets
  const addBoxToSheet = useCallback(async (box) => {
    if (!accessToken) return false;
    
    setSyncStatus('writing');
    
    try {
      const rowData = boxToRow(box);
      await appendSheetRow(rowData, accessToken);
      setSyncStatus('success');
      return true;
    } catch (error) {
      console.error('Failed to add box to sheet:', error);
      setSyncStatus('error');
      return false;
    }
  }, [accessToken]);
  
  // Show splash screen, but don't load data until signed in
  useEffect(() => {
    // Just show splash screen for minimum duration
    setTimeout(() => {
      setSplashDelay(false);
      setDataLoading(false);
    }, 2000);
  }, []);
  
  // Valid Cuban cigar brands (for filtering)
  const validBrands = ['Cohiba', 'Trinidad', 'Montecristo', 'Partagas', 'Bolivar', 'Hoyo de Monterrey', 'H. Upmann', 'Ramon Allones', 'Romeo y Julieta', 'Punch', 'Cuaba', 'Diplomaticos', 'El Rey del Mundo', 'Fonseca', 'Jose L. Piedra', 'Juan Lopez', 'La Flor de Cano', 'La Gloria Cubana', 'Por Larranaga', 'Quai d\'Orsay', 'Quintero', 'Rafael Gonzalez', 'Saint Luis Rey', 'San Cristobal de la Habana', 'Sancho Panza', 'Vegas Robaina', 'Vegueros'];
  
  // Function to expand a row into multiple boxes based on quantity (for refresh)
  const expandRowToBoxesRefresh = (row, rowIndex) => {
    const qty = parseInt(row[5]) || 1;
    const boxNumStr = row[1] || '';
    const boxNums = boxNumStr.split(',').map(s => s.trim()).filter(s => s);
    const perBox = parseInt(row[6]) || 0;
    const totalRemaining = parseInt(row[15]) || 0;
    const totalConsumed = parseInt(row[14]) || 0;
    
    if (qty <= 1) {
      return [rowToBox(row, rowIndex * 100)];
    }
    
    const boxes = [];
    const remainingPerBox = Math.floor(totalRemaining / qty);
    const consumedPerBox = Math.floor(totalConsumed / qty);
    let remainingRemainder = totalRemaining % qty;
    let consumedRemainder = totalConsumed % qty;
    
    for (let i = 0; i < qty; i++) {
      const boxNum = boxNums[i] || `${boxNumStr}.${i + 1}`;
      const thisRemaining = remainingPerBox + (remainingRemainder > 0 ? 1 : 0);
      const thisConsumed = consumedPerBox + (consumedRemainder > 0 ? 1 : 0);
      if (remainingRemainder > 0) remainingRemainder--;
      if (consumedRemainder > 0) consumedRemainder--;
      
      boxes.push({
        id: rowIndex * 100 + i + 1,
        datePurchased: parseDate(row[0]),
        boxNum: boxNum,
        received: row[2] === 'TRUE',
        brand: row[3] || '',
        name: row[4] || '',
        qty: 1,
        perBox: perBox,
        currency: row[7] || 'USD',
        price: parseCurrency(row[8]),
        pricePerCigar: parseCurrency(row[9]),
        status: row[10] || 'Ageing',
        dateOfBox: parseDate(row[11]),
        code: row[12] || '',
        location: row[13] || 'Cayman',
        consumed: thisConsumed,
        remaining: thisRemaining,
        ringGauge: row[16] || '',
length: row[17] || '',
vitola: row[18] || '',
boxNotes: row[19] || '',
      });
    }
    return boxes;
  };
  
  // Refresh data from Google Sheets
  const refreshData = async () => {
    if (!googleAccessToken) return;
    
    setSyncStatus('syncing');
    try {
      const collectionRows = await fetchSheetData(googleAccessToken);
      if (collectionRows) {
        const boxData = collectionRows
  .filter(row => {
    const brand = row[3]?.trim();
    const name = row[4]?.trim();
    const perBox = parseInt(row[6]);
    return brand && name && perBox > 0;
  })
  .flatMap((row, idx) => expandRowToBoxesRefresh(row, idx));
setBoxes(boxData);
      }
      
      const onwardsRows = await fetchOnwardsData(googleAccessToken);
if (onwardsRows) {
  const onwardsData = onwardsRows
    .slice(2)
    .filter(row => {
      const brand = row[2]?.trim();
      const name = row[3]?.trim();
      return brand && name;
    })
    .map((row, idx) => rowToOnwards(row, idx));
  setOnwards(onwardsData);
}
      
      // Refresh history data
      const historyRows = await fetchHistoryData(googleAccessToken);
      if (historyRows && historyRows.length > 1) {
        const historyData = historyRows.slice(1).map(row => ({
          date: row[0],
          boxNum: row[1],
          brand: row[2],
          name: row[3],
          qty: parseInt(row[4]) || 1,
          notes: row[5] || '',
          source: row[1] === 'EXT' ? 'external' : 'collection',
          timestamp: Date.now()
        }));
        setHistory(historyData);
      }
      
      setSyncStatus('success');
    } catch (error) {
      setSyncStatus('error');
    }
  };
  
  // Fetch live exchange rate on mount
  useEffect(() => {
    const fetchExchangeRate = async () => {
      try {
        // Using frankfurter.app - free, no API key required
        const response = await fetch('https://api.frankfurter.app/latest?from=USD&to=GBP');
        if (response.ok) {
          const data = await response.json();
          if (data.rates && data.rates.GBP) {
            setFxRate(data.rates.GBP);
            setFxUpdated(new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }));
          }
        }
      } catch (error) {
        console.log('Using default exchange rate');
      } finally {
        setFxLoading(false);
      }
    };
    fetchExchangeRate();
  }, []);
  
  // Create FX object with current rate
  const FX = useMemo(() => ({
    rate: fxRate,
    updated: fxUpdated,
    toGBP: (usd) => usd * fxRate,
    toUSD: (gbp) => gbp / fxRate
  }), [fxRate, fxUpdated]);
  
  // Format value in base currency (converts from original currency)
  const fmtCurrency = (amount, fromCurrency = 'USD') => {
    if (amount === undefined || amount === null || isNaN(amount)) return fmt.currency(0, baseCurrency);
    const converted = convertCurrency(amount, fromCurrency, baseCurrency, fxRates);
    if (converted === undefined || converted === null || isNaN(converted)) return fmt.currency(0, baseCurrency);
    return fmt.currency(converted, baseCurrency);
  };
  
  // Format with original currency in brackets if different from base
  const fmtCurrencyWithOriginal = (amount, fromCurrency) => {
    if (!amount || isNaN(amount)) return fmt.currency(0, baseCurrency);
    const baseAmount = convertCurrency(amount, fromCurrency, baseCurrency, fxRates);
    if (fromCurrency === baseCurrency) {
      return fmt.currency(baseAmount, baseCurrency);
    }
    return `${fmt.currency(baseAmount, baseCurrency)} (${fmt.currency(amount, fromCurrency)})`;
  };
  
  // Format GBP value in base currency (for UK market prices)
  const fmtFromGBP = (gbpValue) => {
    if (!gbpValue || isNaN(gbpValue)) return fmt.currency(0, baseCurrency);
    const converted = convertCurrency(gbpValue, 'GBP', baseCurrency, fxRates);
    return fmt.currency(converted, baseCurrency);
  };
  
  // Handle smoke logging - updates local state AND Google Sheets
  const handleLog = async (logEntry) => {
    // For external cigars, just log to history
    if (logEntry.source === 'external') {
      setHistory(prev => [...prev, { ...logEntry, timestamp: Date.now() }]);
      if (isSignedIn && accessToken) {
        await addHistoryEntry(logEntry, accessToken);
      }
      return;
    }
    
    // For collection cigars, update box counts
    const updatedBox = boxes.find(b => b.boxNum === logEntry.boxNum);
    if (!updatedBox) return;
    
    const newRemaining = updatedBox.remaining - logEntry.qty;
    const newConsumed = updatedBox.consumed + logEntry.qty;
    
    setBoxes(prev => prev.map(b => 
      b.boxNum === logEntry.boxNum 
        ? { ...b, remaining: newRemaining, consumed: newConsumed }
        : b
    ));
    setHistory(prev => [...prev, { ...logEntry, timestamp: Date.now() }]);
    
    // Write to Google Sheets if signed in
    if (isSignedIn && accessToken) {
      await updateBoxConsumed({ ...updatedBox, remaining: newRemaining, consumed: newConsumed });
      await addHistoryEntry(logEntry, accessToken);
    }
  };
  
  // Handle delete history entry - reverses the smoke and updates Google Sheets
  const handleDeleteHistory = async (index, entry) => {
    // For external cigars, just remove from history
    if (entry.source === 'external' || entry.boxNum === 'EXT') {
      setHistory(prev => prev.filter((_, i) => i !== index));
      if (isSignedIn && accessToken) {
        await deleteHistoryEntry(entry, accessToken);
      }
      return;
    }
    
    // For collection cigars, reverse the consumed/remaining
    const box = boxes.find(b => b.boxNum === entry.boxNum);
    if (!box) return;
    
    const newRemaining = box.remaining + entry.qty;
    const newConsumed = box.consumed - entry.qty;
    
    // Update local state
    setBoxes(prev => prev.map(b => 
      b.boxNum === entry.boxNum 
        ? { ...b, remaining: newRemaining, consumed: newConsumed }
        : b
    ));
    setHistory(prev => prev.filter((_, i) => i !== index));
    
    // Update Google Sheets if signed in
    if (isSignedIn && accessToken) {
      await updateBoxConsumed({ ...box, remaining: newRemaining, consumed: newConsumed });
      await deleteHistoryEntry(entry, accessToken);
    }
  };
  
  // Handle edit history entry
  const handleEditHistory = (index, entry) => {
    setEditingHistory({ index, entry });
  };
  
  // Handle adding new boxes - updates local state AND Google Sheets
  const handleAddBoxes = async (newBoxes) => {
    // Update local state first for instant UI feedback
    setBoxes(prev => [...prev, ...newBoxes]);
    
    // Find the highest box number from the new boxes
    const newHighest = Math.max(...newBoxes.map(b => {
      const match = b.boxNum.match(/^(\d+)/);
      return match ? parseInt(match[1]) : 0;
    }));
    
    // Update local state for highest box num
    if (newHighest > highestBoxNum) {
      setHighestBoxNum(newHighest);
    }
    
    // Write to Google Sheets if signed in
    if (isSignedIn && accessToken) {
      for (const box of newBoxes) {
        await addBoxToSheet(box);
      }
      
      // Update highest box number in Settings
      if (newHighest > highestBoxNum) {
        await updateHighestBoxNum(newHighest, accessToken);
      }
    }
  };
  
  const filtered = useMemo(() => {
    let result = boxes.filter(b => b.remaining > 0); // Exclude finished boxes from main collection
    if (location.length > 0) result = result.filter(b => location.includes(b.location));
    if (selectedBrand !== 'All') result = result.filter(b => b.brand === selectedBrand);
    if (selectedStatus.length > 0) result = result.filter(b => selectedStatus.includes(b.status));
    return result;
  }, [boxes, location, selectedBrand, selectedStatus]);

  // Finished boxes for Collection History
  const finishedBoxes = useMemo(() => {
    return boxes.filter(b => b.remaining === 0);
  }, [boxes]);
  
  const finishedGroups = useMemo(() => {
    const g = groupBoxes(finishedBoxes);
    return g.sort((a, b) => {
      if (a.brand !== b.brand) return a.brand.localeCompare(b.brand);
      return a.name.localeCompare(b.name);
    });
  }, [finishedBoxes]);
  
  const finishedGroupsByBrand = useMemo(() => {
    const byBrand = {};
    finishedGroups.forEach(g => {
      if (!byBrand[g.brand]) byBrand[g.brand] = [];
      byBrand[g.brand].push(g);
    });
    return byBrand;
  }, [finishedGroups]);
  
  // Get unique locations for the location selector
  const availableLocations = useMemo(() => {
    return [...new Set(boxes.map(b => b.location).filter(Boolean))].sort();
  }, [boxes]);
  
  // Get unique brands for the brand selector
  const availableBrands = useMemo(() => {
    const brands = [...new Set(boxes.map(b => b.brand))].sort();
    return ['All', ...brands];
  }, [boxes]);
  
  const groups = useMemo(() => {
    const g = groupBoxes(filtered);
    // Sort by brand, then alphabetically by name within brand
    return g.sort((a, b) => {
      if (a.brand !== b.brand) return a.brand.localeCompare(b.brand);
      return a.name.localeCompare(b.name);
    });
  }, [filtered]);
  
  // Group the sorted groups by brand for display
  const groupsByBrand = useMemo(() => {
    const byBrand = {};
    groups.forEach(g => {
      if (!byBrand[g.brand]) byBrand[g.brand] = [];
      byBrand[g.brand].push(g);
    });
    return byBrand;
  }, [groups]);
  
  // Calculate max lengths for uniform card sizing
  const maxLengths = useMemo(() => {
    let maxBrand = 0;
    let maxName = 0;
    groups.forEach(g => {
      if (g.brand.length > maxBrand) maxBrand = g.brand.length;
      if (g.name.length > maxName) maxName = g.name.length;
    });
    return { maxBrand, maxName };
  }, [groups]);
  
 const stats = useMemo(() => {
    const totalCigars = boxes.reduce((s, b) => s + b.remaining, 0);
    const totalBoxes = boxes.length;
    const consumed = boxes.reduce((s, b) => s + b.consumed, 0);
    
    // Convert all prices to base currency
    const getBoxPriceInBase = (b) => convertCurrency(b.price || 0, b.currency || 'USD', baseCurrency, fxRates);
    
    const totalCost = boxes.reduce((s, b) => s + getBoxPriceInBase(b), 0);
    const remainingCost = boxes.reduce((s, b) => {
      if (b.perBox === 0) return s;
      return s + (getBoxPriceInBase(b) * (b.remaining / b.perBox));
    }, 0);
    
    let totalMarket = 0, remainingMarket = 0;
    boxes.forEach(b => {
      const m = getMarket(b.brand, b.name, b.perBox);
      const boxPriceInBase = getBoxPriceInBase(b);
      const marketGBP = m ? m.gbp : 0;
      const marketInBase = convertCurrency(marketGBP, 'GBP', baseCurrency, fxRates);
      totalMarket += marketInBase;
      if (b.perBox > 0) {
        remainingMarket += marketInBase * (b.remaining / b.perBox);
      }
    });
    
    const totalSavings = totalMarket - totalCost;
    const remainingSavings = remainingMarket - remainingCost;
    const onwardsProfit = onwards.reduce((s, o) => s + (o.profitUSD || 0), 0);
    const onwardsCost = onwards.reduce((s, o) => s + o.costUSD, 0);
    
    return { 
      totalCigars, totalBoxes, consumed, 
      totalCostUSD: totalCost, remainingCostUSD: remainingCost, 
      totalMarketUSD: totalMarket, remainingMarketUSD: remainingMarket, 
      totalSavingsUSD: totalSavings, remainingSavingsUSD: remainingSavings, 
      onwardsProfit, onwardsCost, onwardsBoxes: onwards.length 
    };
  }, [boxes, onwards, baseCurrency, fxRates]);

  // Show loading/sign-in screen
  if (dataLoading || splashDelay || !isSignedIn) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: '#1a120b' }}>
        <div className="text-center">
          <h1 className="text-2xl tracking-widest font-semibold mb-2" style={{ color: '#d4af37', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>LA COLECCIÓN</h1>
          <div className="text-sm text-gray-500 mb-4">by Ramy El-Madany</div>
          {splashDelay ? (
            <div className="text-gray-400">Loading...</div>
          ) : dataLoading ? (
            <div className="text-gray-400">Loading from Google Sheets...</div>
          ) : (
            <button 
              onClick={handleGoogleSignIn}
              className="mt-4 px-6 py-3 rounded-lg font-semibold"
              style={{ background: '#F5DEB3', color: '#1a120b' }}
            >
              Sign In with Google
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div 
  className="min-h-screen pb-24" 
  style={{ background: '#1a120b', fontFamily: 'Georgia, serif', overscrollBehavior: 'none' }}
  onTouchStart={(e) => {
    if (window.scrollY <= 2 && !isRefreshing) {
      setPullStart(e.touches[0].clientY);
    }
  }}
  onTouchMove={(e) => {
    if (pullStart > 0 && !isRefreshing) {
      if (window.scrollY > 2) {
        setPullStart(0);
        setPullDistance(0);
        return;
      }
      const currentY = e.touches[0].clientY;
      const distance = currentY - pullStart;
      if (distance > 0) {
        e.preventDefault();
        setPullDistance(Math.min(distance * 0.4, 100));
      }
    }
  }}
  onTouchEnd={async () => {
    if (pullDistance > 50 && !isRefreshing) {
      setIsRefreshing(true);
      await refreshData();
      setIsRefreshing(false);
    }
    setPullStart(0);
    setPullDistance(0);
  }}
>

      {/* Pull to refresh indicator */}
      <div 
        className="flex flex-col items-center justify-center overflow-hidden"
        style={{ 
          height: isRefreshing ? 60 : pullDistance,
          background: '#1a120b',
          transition: pullDistance === 0 ? 'height 0.3s ease-out' : 'none'
        }}
      >
        {(pullDistance > 0 || isRefreshing) && (
          <>
            <div 
              className="w-8 h-8 flex items-center justify-center"
              style={{ 
                transform: isRefreshing ? 'none' : `rotate(${pullDistance * 3}deg)`,
                animation: isRefreshing ? 'spin 0.8s linear infinite' : 'none'
              }}
            >
              <svg 
                width="24" 
                height="24" 
                viewBox="0 0 24 24"
                style={{ opacity: pullDistance > 60 || isRefreshing ? 1 : 0.5 }}
              >
                <rect x="2" y="10" width="18" height="4" rx="2" fill="#8B4513"/>
                <rect x="4" y="10" width="3" height="4" fill="#6B1E1E"/>
                <rect x="20" y="10" width="2" height="4" rx="1" fill="#F5DEB3"/>
                <path d="M21 9 Q22 7 21 5" stroke="#F5DEB3" strokeWidth="0.8" fill="none" opacity="0.6"/>
                <path d="M22 8 Q23 6 22 4" stroke="#F5DEB3" strokeWidth="0.8" fill="none" opacity="0.4"/>
              </svg>
            </div>
            <div 
              className="text-xs mt-2"
              style={{ color: pullDistance > 60 || isRefreshing ? '#d4af37' : '#666' }}
            >
              {isRefreshing ? 'Refreshing...' : pullDistance > 60 ? 'Release' : 'Pull to refresh'}
            </div>
          </>
        )}
      </div>
      
      {/* Header */}
      <div className="sticky top-0 z-40 px-4 py-4" style={{ background: '#1a120b' }}>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl tracking-widest font-semibold" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>LA COLECCIÓN</h1>
          <div className="flex items-center gap-3">
            {view === 'collection' && (
              <button 
                onClick={() => setFilterOpen(true)}
                className="relative px-3 py-1.5 rounded text-sm"
                style={{ color: '#F5DEB3', border: '1px solid #F5DEB3' }}
              >
                Filter
                {(location.length > 0 && !location.includes('All') || selectedBrand !== 'All' || selectedStatus.length > 0) && (
  <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full" style={{ background: '#F5DEB3' }}></span>
)}
              </button>
            )}
            <button 
              onClick={() => setMenuOpen(true)}
              className="w-10 h-10 flex flex-col items-center justify-center gap-1.5"
            >
              <div className="w-6 h-0.5" style={{ background: '#F5DEB3' }}></div>
              <div className="w-6 h-0.5" style={{ background: '#F5DEB3' }}></div>
              <div className="w-6 h-0.5" style={{ background: '#F5DEB3' }}></div>
            </button>
          </div>
        </div>
      </div>

      {/* Slide-in Menu */}
      {menuOpen && (
        <div className="fixed inset-0 z-50" onClick={() => setMenuOpen(false)}>
          <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.8)' }}></div>
          <div 
            className="absolute top-0 right-0 h-full w-72 p-6 overflow-y-auto"
            style={{ background: '#1a1a1a', borderLeft: '1px solid #333' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-8">
              <span className="text-lg" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Menu</span>
              <button onClick={() => setMenuOpen(false)} className="text-2xl text-gray-500">×</button>
            </div>
            
         {/* Navigation */}
            <div className="space-y-2 mb-6">
              {['collection', 'value', 'collection-history', 'history', 'onwards', 'prices', 'settings'].map(v => {
                const displayNames = {
                  'collection': 'Collection',
                  'value': 'Collection Value',
                  'collection-history': 'Collection History',
                  'history': 'Logged Smokes',
                  'onwards': 'Onwards',
                  'prices': 'Prices',
                  'settings': 'Settings'
                };
                return (
                  <button 
                    key={v} 
                    onClick={() => { setView(v); setMenuOpen(false); }}
                    className="w-full text-left py-3 px-4 rounded-lg"
                    style={{
                      background: view === v ? '#F5DEB320' : 'transparent',
                      color: view === v ? '#F5DEB3' : '#888'
                    }}
                  >
                    {displayNames[v]}
                  </button>
                );
              })}
            </div>
            
         {/* Sign In/Out */}
            <div className="border-t border-gray-700 pt-6 space-y-4">
              <div>
                {!isSignedIn ? (
                  <button 
                    onClick={() => { handleGoogleSignIn(); setMenuOpen(false); }}
                    className="w-full py-3 rounded-lg text-center font-semibold"
                    style={{ background: '#F5DEB3', color: '#1a120b' }}
                  >
                    Sign In with Google
                  </button>
                ) : (
                  <button 
                    onClick={() => { handleGoogleSignOut(); setMenuOpen(false); }}
                    className="w-full py-3 rounded-lg text-center"
                    style={{ background: '#252525', color: '#888', border: '1px solid #444' }}
                  >
                    Sign Out
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

{/* Filter Panel */}
      {filterOpen && (
        <div className="fixed inset-0 z-50 flex items-end" onClick={() => setFilterOpen(false)}>
          <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,0.8)' }}></div>
          <div 
            className="relative w-full rounded-t-2xl p-6 max-h-[70vh] overflow-y-auto"
            style={{ background: '#1a1a1a', border: '1px solid #333' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-6">
              <span className="text-lg" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Filters</span>
              <button onClick={() => setFilterOpen(false)} className="text-2xl text-gray-500">×</button>
            </div>
            
            {/* Location Filter */}
            <div className="mb-6">
              <div className="text-sm text-gray-500 mb-3">Location</div>
              <div className="flex gap-2 flex-wrap">
                {availableLocations.map(l => (
                  <button 
                    key={l} 
                    onClick={() => {
                      if (location.includes(l)) {
                        setLocation(location.filter(loc => loc !== l));
                      } else {
                        setLocation([...location, l]);
                      }
                    }} 
                    className="px-4 py-2 rounded-lg text-sm"
                    style={{
                      background: location.includes(l) ? '#F5DEB3' : '#252525',
                      color: location.includes(l) ? '#000' : '#888',
                      border: location.includes(l) ? 'none' : '1px solid #444'
                    }}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
            
            {/* Brand Filter */}
            <div className="mb-6">
              <div className="text-sm text-gray-500 mb-3">Brand</div>
              <div className="flex gap-2 flex-wrap">
                {availableBrands.map(brand => (
                  <button 
                    key={brand} 
                    onClick={() => setSelectedBrand(brand)} 
                    className="px-3 py-2 rounded-lg text-sm"
                    style={{
                      background: selectedBrand === brand ? '#F5DEB3' : '#252525',
                      color: selectedBrand === brand ? '#000' : '#888',
                      border: selectedBrand === brand ? 'none' : '1px solid #444'
                    }}
                  >
                    {brand}
                  </button>
                ))}
              </div>
            </div>
            
            {/* Status Filter */}
<div className="mb-6">
  <div className="text-sm text-gray-500 mb-3">Status</div>
  <div className="flex gap-2 flex-wrap">
    {['Ageing', 'Immediate', 'Combination'].map(s => (
      <button 
        key={s}
        onClick={() => {
          if (selectedStatus.includes(s)) {
            setSelectedStatus(selectedStatus.filter(st => st !== s));
          } else {
            setSelectedStatus([...selectedStatus, s]);
          }
        }} 
        className="px-4 py-2 rounded-lg text-sm"
        style={{
          background: selectedStatus.includes(s) ? '#F5DEB3' : '#252525',
          color: selectedStatus.includes(s) ? '#000' : '#888',
          border: selectedStatus.includes(s) ? 'none' : '1px solid #444'
        }}
      >
        {s === 'Immediate' ? 'On Rotation' : s === 'Combination' ? 'Assortment' : s}
      </button>
    ))}
  </div>
</div>
            
            {/* Clear Filters */}
            <button 
  onClick={() => { setLocation([]); setSelectedBrand('All'); setSelectedStatus([]); }}
  className="w-full py-3 rounded-lg text-sm"
  style={{ background: '#252525', color: '#888', border: '1px solid #444' }}
>
  Clear All Filters
</button>
          </div>
        </div>
      )}
    
     {/* Collection View */}
      {view === 'collection' && (
        <div className="px-4 pt-6">
          {Object.entries(groupsByBrand).map(([brand, brandGroups]) => (
            <div key={brand} className="mb-6">
              {/* Brand Header */}
              <div 
                className="mb-3 pb-2 flex justify-between items-center" 
                style={{ borderBottom: '2px solid #F5DEB3', cursor: 'pointer' }}
                onClick={() => {
                  const newCollapsed = collapsedBrands.includes(brand) 
                    ? collapsedBrands.filter(b => b !== brand)
                    : [...collapsedBrands, brand];
                  setCollapsedBrands(newCollapsed);
                  localStorage.setItem('collapsedBrands', JSON.stringify(newCollapsed));
                }}
              >
                <h2 className="text-2xl font-bold tracking-wide" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{brand}</h2>
                <span className="text-xl font-bold" style={{ color: '#F5DEB3' }}>
                  {collapsedBrands.includes(brand) ? '+' : '−'}
                </span>
              </div>
              {/* Cigar cards for this brand */}
<div 
  className="grid transition-all duration-300 ease-in-out overflow-hidden"
  style={{ 
    gridTemplateRows: collapsedBrands.includes(brand) ? '0fr' : '1fr'
  }}
>
  <div className="min-h-0">
    <div className="grid grid-cols-2 gap-3 pb-1">
      {brandGroups.map(g => <CigarGroupCard key={`${g.brand}|${g.name}`} group={g} onClick={() => setSelectedGroup(g)} maxLengths={maxLengths} showCigarCount={showCigarCount} />)}
    </div>
  </div>
</div>
            </div>
          ))}
        </div>
      )}

      {/* Collection History View */}
      {view === 'collection-history' && (
        <div className="px-4">
          <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Finished Boxes</h2>
          {Object.keys(finishedGroupsByBrand).length === 0 ? (
            <div className="text-center py-8 text-gray-500">No finished boxes yet</div>
          ) : (
            Object.entries(finishedGroupsByBrand).map(([brand, brandGroups]) => (
              <div key={brand} className="mb-6">
                {/* Brand Header */}
                <div 
                  className="mb-3 pb-2 flex justify-between items-center" 
                  style={{ borderBottom: '2px solid #888', cursor: 'pointer' }}
                  onClick={() => {
                    const newCollapsed = collapsedBrands.includes(`history-${brand}`) 
                      ? collapsedBrands.filter(b => b !== `history-${brand}`)
                      : [...collapsedBrands, `history-${brand}`];
                    setCollapsedBrands(newCollapsed);
                    localStorage.setItem('collapsedBrands', JSON.stringify(newCollapsed));
                  }}
                >
                  <h2 className="text-2xl font-bold tracking-wide" style={{ color: '#888', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{brand}</h2>
                  <span className="text-xl font-bold" style={{ color: '#888' }}>
                    {collapsedBrands.includes(`history-${brand}`) ? '+' : '−'}
                  </span>
                </div>
                {/* Cigar cards for this brand */}
                {!collapsedBrands.includes(`history-${brand}`) && (
                  <div className="grid grid-cols-2 gap-3">
                    {brandGroups.map(g => <CigarGroupCard key={`${g.brand}|${g.name}`} group={g} onClick={() => setSelectedGroup(g)} maxLengths={maxLengths} showCigarCount={showCigarCount} isFinishedView={true} />)}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
      
      {/* Onwards View */}
      {view === 'onwards' && (
        <div className="px-4">
          <div className="grid grid-cols-3 gap-2 mb-4">
            <div className="rounded-lg p-3 text-center" style={{ background: '#1a1a1a', border: '1px solid #333' }}>
              <div className="text-2xl font-light" style={{ color: '#d4af37' }}>{stats.onwardsBoxes}</div>
              <div className="text-xs text-gray-500">Boxes</div>
            </div>
            <div className="rounded-lg p-3 text-center" style={{ background: '#1a1a1a', border: '1px solid #333' }}>
              <div className="text-lg font-light text-gray-400">{fmtCurrency(stats.onwardsCost)}</div>
              <div className="text-xs text-gray-500">Cost</div>
            </div>
            <div className="rounded-lg p-3 text-center" style={{ background: '#1a1a1a', border: '1px solid #333' }}>
              <div className="text-lg font-light text-green-400">+{fmtCurrency(stats.onwardsProfit)}</div>
              <div className="text-xs text-gray-500">Profit</div>
            </div>
          </div>
          <div className="space-y-3">
            {onwards.map(o => <OnwardsCard key={o.id} item={o} fmtCurrency={fmtCurrency} />)}
          </div>
        </div>
      )}

      {/* {/* Value View */}
      {view === 'value' && (
        <div className="px-4 pb-8 pt-4">
          {(() => {
            const remainingBoxes = boxes.filter(b => b.remaining > 0);
            
            // Convert box price to base currency
            const getBoxPriceInBase = (b) => {
              return convertCurrency(b.price || 0, b.currency || 'USD', baseCurrency, fxRates);
            };
            
            const getBoxMarket = (b) => {
              const m = getMarket(b.brand, b.name, b.perBox);
              const marketGBP = m ? m.gbp : null;
              return marketGBP ? convertCurrency(marketGBP, 'GBP', baseCurrency, fxRates) : null;
            };
            
            const hasMarketData = (b) => {
              const m = getMarket(b.brand, b.name, b.perBox);
              return m && m.gbp;
            };
            
            // Calculate average cigar value from boxes WITH known market data
            const boxesWithMarket = remainingBoxes.filter(hasMarketData);
            const cigarsWithMarket = boxesWithMarket.reduce((s, b) => s + b.remaining, 0);
            const marketValueWithData = boxesWithMarket.reduce((s, b) => {
              const market = getBoxMarket(b);
              return s + market * (b.remaining / b.perBox);
            }, 0);
            const avgCigarFromKnown = cigarsWithMarket > 0 ? marketValueWithData / cigarsWithMarket : 0;
            
            const groupByVitola = (boxList) => {
              const groups = {};
              boxList.forEach(b => {
                const key = `${b.brand}|${b.name}`;
                if (!groups[key]) {
                  groups[key] = { brand: b.brand, name: b.name, boxes: [] };
                }
                groups[key].boxes.push(b);
              });
              return Object.values(groups);
            };
            
            const findGroupForBox = (boxNum) => {
              const box = remainingBoxes.find(b => b.boxNum === boxNum);
              if (!box) return null;
              const key = `${box.brand}|${box.name}`;
              const groupBoxes = remainingBoxes.filter(b => `${b.brand}|${b.name}` === key);
              return { brand: box.brand, name: box.name, boxes: groupBoxes };
            };
            
            const fullBoxes = remainingBoxes.filter(b => b.remaining === b.perBox);
            const fullBoxVitolas = groupByVitola(fullBoxes);
            const mostValuableBox = fullBoxVitolas
              .filter(v => hasMarketData(v.boxes[0]))
              .map(v => ({
                ...v,
                marketValue: getBoxMarket(v.boxes[0]),
                boxIds: v.boxes.map(b => b.boxNum)
              }))
              .sort((a, b) => b.marketValue - a.marketValue)
              .slice(0, 3);
            
            const allVitolas = groupByVitola(remainingBoxes);
            const mostValuableCigar = allVitolas
              .filter(v => hasMarketData(v.boxes[0]))
              .map(v => {
                const boxMarket = getBoxMarket(v.boxes[0]);
                const perBox = v.boxes[0].perBox;
                return {
                  ...v,
                  cigarValue: perBox > 0 ? boxMarket / perBox : 0,
                  boxIds: v.boxes.map(b => b.boxNum)
                };
              })
              .sort((a, b) => b.cigarValue - a.cigarValue)
              .slice(0, 3);
            
            // Only include vitolas WITH market data in performance rankings
            const vitolasWithMarket = allVitolas.filter(v => hasMarketData(v.boxes[0]));
            
            const bestPerformer = vitolasWithMarket
              .map(v => {
                const avgPurchase = v.boxes.reduce((s, b) => s + getBoxPriceInBase(b), 0) / v.boxes.length;
                const marketValue = getBoxMarket(v.boxes[0]);
                const returnPct = avgPurchase > 0 ? ((marketValue - avgPurchase) / avgPurchase) * 100 : 0;
                return {
                  ...v,
                  purchasePrice: avgPurchase,
                  marketValue,
                  returnPct,
                  boxIds: v.boxes.map(b => b.boxNum)
                };
              })
              .sort((a, b) => b.returnPct - a.returnPct)
              .slice(0, 3);
            
            const worstPerformer = vitolasWithMarket
              .map(v => {
                const avgPurchase = v.boxes.reduce((s, b) => s + getBoxPriceInBase(b), 0) / v.boxes.length;
                const marketValue = getBoxMarket(v.boxes[0]);
                const returnPct = avgPurchase > 0 ? ((marketValue - avgPurchase) / avgPurchase) * 100 : 0;
                return {
                  ...v,
                  purchasePrice: avgPurchase,
                  marketValue,
                  returnPct,
                  boxIds: v.boxes.map(b => b.boxNum)
                };
              })
              .sort((a, b) => a.returnPct - b.returnPct)
              .slice(0, 3);
            
            const totalCigarsRemaining = remainingBoxes.reduce((s, b) => s + b.remaining, 0);
            // For boxes without market data, use the average from known boxes
            const totalMarketRemaining = remainingBoxes.reduce((s, b) => {
              const market = getBoxMarket(b);
              if (market !== null) {
                return s + market * (b.remaining / b.perBox);
              } else {
                // Use average cigar value for unknown boxes
                return s + avgCigarFromKnown * b.remaining;
              }
            }, 0);
            const avgCigarValue = avgCigarFromKnown;
            
            const totalSmoked = boxes.reduce((s, b) => s + b.consumed, 0);
            const valueEnjoyed = boxes.reduce((s, b) => {
              if (b.perBox === 0) return s;
              const boxMarket = getBoxMarket(b);
              if (boxMarket !== null) {
                return s + (boxMarket / b.perBox) * b.consumed;
              } else {
                return s + avgCigarFromKnown * b.consumed;
              }
            }, 0);
            
            const boxesWithRelease = remainingBoxes.filter(b => b.dateOfBox);
            const oldestBox = boxesWithRelease.length > 0 
              ? boxesWithRelease.sort((a, b) => new Date(a.dateOfBox) - new Date(b.dateOfBox))[0]
              : null;
            
            const boxesWithPurchase = remainingBoxes.filter(b => b.datePurchased);
            const newestAddition = boxesWithPurchase.length > 0
              ? boxesWithPurchase.sort((a, b) => new Date(b.datePurchased) - new Date(a.datePurchased))[0]
              : null;
            
            return (
              <>
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Collection Summary</h2>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg p-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
                      <div className="text-sm font-medium mb-2" style={{ color: 'rgba(26,18,11,0.5)' }}>Current Collection</div>
                      <div className="space-y-1">
                        <div className="flex justify-between">
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>Your Cost</span>
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>{fmtCurrency(stats.remainingCostUSD)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>UK Market</span>
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>{fmtCurrency(stats.remainingMarketUSD)}</span>
                        </div>
                        <div className="flex justify-between pt-1 border-t" style={{ borderColor: '#6B1E1E' }}>
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>Savings</span>
                          <span className="text-sm font-medium" style={{ color: stats.remainingSavingsUSD >= 0 ? '#1a5a1a' : '#6B1E1E' }}>{fmtCurrency(stats.remainingSavingsUSD)}</span>
                        </div>
                      </div>
                    </div>
                    <div className="rounded-lg p-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
                      <div className="text-sm font-medium mb-2" style={{ color: 'rgba(26,18,11,0.5)' }}>Historical Collection</div>
                      <div className="space-y-1">
                        <div className="flex justify-between">
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>Your Cost</span>
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>{fmtCurrency(stats.totalCostUSD)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>UK Market</span>
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>{fmtCurrency(stats.totalMarketUSD)}</span>
                        </div>
                        <div className="flex justify-between pt-1 border-t" style={{ borderColor: '#6B1E1E' }}>
                          <span className="text-sm font-medium" style={{ color: '#1a120b' }}>Savings</span>
                          <span className="text-sm font-medium" style={{ color: stats.totalSavingsUSD >= 0 ? '#1a5a1a' : '#6B1E1E' }}>{fmtCurrency(stats.totalSavingsUSD)}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Most Valuable Box</h2>
                  <div className="space-y-2">
                    {mostValuableBox.map((v, i) => (
                      <div key={i} className="rounded-lg p-3 flex justify-between items-center cursor-pointer" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }} onClick={() => { const group = findGroupForBox(v.boxIds[0]); if (group) setSelectedGroup(group); }}>
                        <div>
                          <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{v.brand}</div>
                          <div className="text-base font-medium" style={{ color: '#1a120b' }}>{v.name}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box {v.boxIds.join(', ')}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xl font-medium" style={{ color: '#1a120b' }}>{fmtCurrency(v.marketValue)}</div>
                        </div>
                      </div>
                    ))}
                    {mostValuableBox.length === 0 && <div className="text-sm font-medium" style={{ color: 'rgba(245,222,179,0.5)' }}>No full boxes with market data</div>}
                  </div>
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Most Valuable Cigar</h2>
                  <div className="space-y-2">
                    {mostValuableCigar.map((v, i) => (
                      <div key={i} className="rounded-lg p-3 flex justify-between items-center cursor-pointer" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }} onClick={() => { const group = findGroupForBox(v.boxIds[0]); if (group) setSelectedGroup(group); }}>
                        <div>
                          <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{v.brand}</div>
                          <div className="text-base font-medium" style={{ color: '#1a120b' }}>{v.name}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box {v.boxIds.join(', ')}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xl font-medium" style={{ color: '#1a120b' }}>{fmtCurrency(v.cigarValue)}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>per cigar</div>
                        </div>
                      </div>
                    ))}
                    {mostValuableCigar.length === 0 && <div className="text-sm font-medium" style={{ color: 'rgba(245,222,179,0.5)' }}>No cigars with market data</div>}
                  </div>
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Best Performer</h2>
                  <div className="space-y-2">
                    {bestPerformer.map((v, i) => (
                      <div key={i} className="rounded-lg p-3 flex justify-between items-center cursor-pointer" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }} onClick={() => { const group = findGroupForBox(v.boxIds[0]); if (group) setSelectedGroup(group); }}>
                        <div>
                          <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{v.brand}</div>
                          <div className="text-base font-medium" style={{ color: '#1a120b' }}>{v.name}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box {v.boxIds.join(', ')}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xl font-medium" style={{ color: v.returnPct >= 0 ? '#1a5a1a' : '#6B1E1E' }}>
                            {v.returnPct >= 0 ? '+' : ''}{v.returnPct.toFixed(1)}%
                          </div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>{fmtCurrency(v.purchasePrice)} → {fmtCurrency(v.marketValue)}</div>
                        </div>
                      </div>
                    ))}
                    {bestPerformer.length === 0 && <div className="text-sm font-medium" style={{ color: 'rgba(245,222,179,0.5)' }}>No cigars with market data</div>}
                  </div>
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Worst Performer</h2>
                  <div className="space-y-2">
                    {worstPerformer.map((v, i) => (
                      <div key={i} className="rounded-lg p-3 flex justify-between items-center cursor-pointer" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }} onClick={() => { const group = findGroupForBox(v.boxIds[0]); if (group) setSelectedGroup(group); }}>
                        <div>
                          <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{v.brand}</div>
                          <div className="text-base font-medium" style={{ color: '#1a120b' }}>{v.name}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box {v.boxIds.join(', ')}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xl font-medium" style={{ color: v.returnPct >= 0 ? '#1a5a1a' : '#6B1E1E' }}>
                            {v.returnPct >= 0 ? '+' : ''}{v.returnPct.toFixed(1)}%
                          </div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>{fmtCurrency(v.purchasePrice)} → {fmtCurrency(v.marketValue)}</div>
                        </div>
                      </div>
                    ))}
                    {worstPerformer.length === 0 && <div className="text-sm font-medium" style={{ color: 'rgba(245,222,179,0.5)' }}>No cigars with market data</div>}
                  </div>
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Average Cigar Value</h2>
                  <div className="rounded-lg p-4 text-center" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
                    <div className="text-4xl font-medium" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{fmtCurrency(avgCigarValue)}</div>
                    <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>per cigar (market value)</div>
                  </div>
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Cigars Enjoyed</h2>
                  <div className="rounded-lg p-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
                    <div className="flex justify-between items-center">
                      <div>
                        <div className="text-4xl font-medium" style={{ color: '#6B1E1E', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{totalSmoked}</div>
                        <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>cigars smoked</div>
                      </div>
                      <div className="text-right">
                        <div className="text-2xl font-medium" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{fmtCurrency(valueEnjoyed)}</div>
                        <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>estimated value</div>
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Oldest Box</h2>
                  {oldestBox ? (
                    <div className="rounded-lg p-4 cursor-pointer" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }} onClick={() => { const group = findGroupForBox(oldestBox.boxNum); if (group) setSelectedGroup(group); }}>
                      <div className="flex justify-between items-center">
                        <div>
                          <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{oldestBox.brand}</div>
                          <div className="text-base font-medium" style={{ color: '#1a120b' }}>{oldestBox.name}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box {oldestBox.boxNum}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xl font-medium" style={{ color: '#1a120b' }}>{fmt.monthYear(oldestBox.dateOfBox)}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>release date</div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm font-medium" style={{ color: 'rgba(245,222,179,0.5)' }}>No release dates recorded</div>
                  )}
                </div>
                
                <div className="mb-6">
                  <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Newest Addition</h2>
                  {newestAddition ? (
                    <div className="rounded-lg p-4 cursor-pointer" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }} onClick={() => { const group = findGroupForBox(newestAddition.boxNum); if (group) setSelectedGroup(group); }}>
                      <div className="flex justify-between items-center">
                        <div>
                          <div className="text-lg font-bold" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>{newestAddition.brand}</div>
                          <div className="text-base font-medium" style={{ color: '#1a120b' }}>{newestAddition.name}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>Box {newestAddition.boxNum}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xl font-medium" style={{ color: '#1a120b' }}>{fmt.date(newestAddition.datePurchased)}</div>
                          <div className="text-sm font-medium" style={{ color: 'rgba(26,18,11,0.5)' }}>purchased</div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm font-medium" style={{ color: 'rgba(245,222,179,0.5)' }}>No purchase dates recorded</div>
                  )}
                </div>
              </>
            );
          })()}
        </div>
      )}
      
      {/* History View */}
{view === 'history' && <HistoryView history={history} boxes={boxes} onDelete={isSignedIn ? handleDeleteHistory : () => setShowSignInPrompt(true)} onEdit={isSignedIn ? handleEditHistory : () => setShowSignInPrompt(true)} onBoxClick={(group, boxNum) => { const boxIndex = group.boxes.findIndex(b => b.boxNum === boxNum); setSelectedGroup({ ...group, initialBoxIndex: boxIndex >= 0 ? boxIndex : 0 }); }} />}      
      {/* Prices View */}
      {view === 'prices' && <PricesView boxes={boxes} currency={currency} FX={FX} fmtCurrency={fmtCurrency} fmtFromGBP={fmtFromGBP} />}
      {/* Settings View */}
{view === 'settings' && (
  <div className="px-4 pb-8 pt-4">
    <div className="mb-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Settings</h2>
      
      {/* Base Currency */}
      <div className="rounded-lg p-4 mb-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
        <div className="flex justify-between items-center">
          <div>
            <div className="text-base font-medium" style={{ color: '#1a120b' }}>Base Currency</div>
            <div className="text-sm" style={{ color: 'rgba(26,18,11,0.5)' }}>Display prices in this currency</div>
          </div>
          <select 
            value={baseCurrency} 
            onChange={async (e) => {
              const newCurrency = e.target.value;
              setBaseCurrency(newCurrency);
              localStorage.setItem('baseCurrency', newCurrency);
              if (isSignedIn && accessToken) {
                await saveSetting('baseCurrency', newCurrency, accessToken);
              }
              // Refresh FX rates for new base
              const fxData = await fetchFxRates(newCurrency);
              if (fxData) {
                setFxRates(fxData.rates);
                setFxLastUpdated(fxData.date);
              }
            }}
            className="px-3 py-2 rounded-lg text-base font-medium"
            style={{ background: '#1a120b', color: '#F5DEB3', border: 'none' }}
          >
            {CURRENCIES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>
      
      {/* Show Cigar Count */}
      <div className="rounded-lg p-4 mb-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
        <div className="flex justify-between items-center">
          <div>
            <div className="text-base font-medium" style={{ color: '#1a120b' }}>Show Cigar Count</div>
            <div className="text-sm" style={{ color: 'rgba(26,18,11,0.5)' }}>Display count on collection cards</div>
          </div>
          <button
            onClick={async () => {
              const newValue = !showCigarCount;
              setShowCigarCount(newValue);
              localStorage.setItem('showCigarCount', JSON.stringify(newValue));
              if (isSignedIn && accessToken) {
                await saveSetting('showCigarCount', newValue, accessToken);
              }
            }}
            className="px-4 py-2 rounded-lg text-base font-medium"
            style={{ 
              background: showCigarCount ? '#1a5a1a' : '#1a120b', 
              color: showCigarCount ? '#90EE90' : '#888' 
            }}
          >
            {showCigarCount ? 'On' : 'Off'}
          </button>
        </div>
      </div>
    </div>
    
    {/* Account Section */}
    <div className="mb-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>Account</h2>
      
      <div className="rounded-lg p-4" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
        <div className="flex justify-between items-center">
          <div>
            <div className="text-base font-medium" style={{ color: '#1a120b' }}>
              {isSignedIn ? 'Signed In' : 'Not Signed In'}
            </div>
            <div className="text-sm" style={{ color: 'rgba(26,18,11,0.5)' }}>
              {isSignedIn ? 'Syncing with Google Sheets' : 'Sign in to sync data'}
            </div>
          </div>
          {isSignedIn ? (
            <button
              onClick={handleGoogleSignOut}
              className="px-4 py-2 rounded-lg text-base font-medium"
              style={{ background: '#6B1E1E', color: '#F5DEB3' }}
            >
              Sign Out
            </button>
          ) : (
            <button
              onClick={handleGoogleSignIn}
              className="px-4 py-2 rounded-lg text-base font-medium"
              style={{ background: '#1a120b', color: '#F5DEB3' }}
            >
              Sign In
            </button>
          )}
        </div>
      </div>
    </div>
    
    {/* App Info */}
    <div className="mb-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: '#F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>About</h2>
      
      <div className="rounded-lg p-4 text-center" style={{ background: 'linear-gradient(145deg, #F5DEB3, #E8D4A0)' }}>
        <div className="text-lg font-bold mb-1" style={{ color: '#1a120b', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>La Colección</div>
        <div className="text-sm" style={{ color: 'rgba(26,18,11,0.5)' }}>by Ramy El-Madany</div>
        <div className="text-xs mt-2" style={{ color: 'rgba(26,18,11,0.4)' }}>v1.0.0</div>
      </div>
    </div>
  </div>
)}
      {/* Modals */}
      {selectedGroup && <BoxDetailModal boxes={selectedGroup.boxes} initialBoxIndex={selectedGroup.initialBoxIndex || 0} onClose={() => setSelectedGroup(null)} fmtCurrency={fmtCurrency} fmtCurrencyWithOriginal={fmtCurrencyWithOriginal} fmtFromGBP={fmtFromGBP} baseCurrency={baseCurrency} fxRates={fxRates} isSignedIn={!!googleAccessToken} onDelete={async (box) => { if (!googleAccessToken) return false; const success = await deleteSheetRow(box.boxNum, googleAccessToken); if (success) { await refreshData(); const remainingBoxes = selectedGroup.boxes.filter(b => b.boxNum !== box.boxNum); if (remainingBoxes.length > 0) { setSelectedGroup({ ...selectedGroup, boxes: remainingBoxes }); } else { setSelectedGroup(null); } } return success; }} onEdit={async (box, updatedData) => { if (!googleAccessToken) return false; const success = await updateBoxInSheet(box.boxNum, updatedData, googleAccessToken); if (success) { const updatedGroupBoxes = selectedGroup.boxes.map(b => b.boxNum === box.boxNum ? { ...b, ...updatedData } : b); setSelectedGroup({ ...selectedGroup, boxes: updatedGroupBoxes }); refreshData(); } return success; }} availableLocations={availableLocations} />}
      {showLogModal && <SmokeLogModal boxes={boxes} onClose={() => setShowLogModal(false)} onLog={handleLog} />}
      {showAddModal && <AddBoxModal boxes={boxes} onClose={() => setShowAddModal(false)} onAdd={handleAddBoxes} highestBoxNum={highestBoxNum} />}
      {showSignInPrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.9)' }}>
          <div className="w-full max-w-sm rounded-xl p-6 text-center" style={{ background: '#1a1a1a', border: '1px solid #333' }}>
            <div className="text-4xl mb-4">🔐</div>
            <h3 className="text-xl font-semibold mb-2" style={{ color: '#d4af37' }}>Sign In Required</h3>
            <p className="text-gray-400 mb-6">Please sign in with Google to make changes. This ensures your data is saved to your collection.</p>
            <div className="flex gap-3">
              <button 
                onClick={() => setShowSignInPrompt(false)} 
                className="flex-1 py-3 rounded-lg font-semibold"
                style={{ background: '#333', color: '#888' }}
              >
                Cancel
              </button>
              <button 
                onClick={() => { setShowSignInPrompt(false); handleGoogleSignIn(); }} 
                className="flex-1 py-3 rounded-lg font-semibold"
                style={{ background: '#d4af37', color: '#000' }}
              >
                Sign In
              </button>
            </div>
          </div>
        </div>
      )}

      {editingHistory && <EditHistoryModal 
  entry={editingHistory.entry} 
  index={editingHistory.index}
  onClose={() => setEditingHistory(null)} 
  onSave={async (index, oldEntry, newEntry) => {
    // Update local state and close modal immediately for instant UI feedback
    setHistory(prev => prev.map((h, i) => i === index ? { ...newEntry, timestamp: Date.now() } : h));
    setEditingHistory(null);
    
    // If collection cigar and qty changed, update box counts
    if (oldEntry.boxNum !== 'EXT' && oldEntry.source !== 'external') {
      const qtyDiff = newEntry.qty - oldEntry.qty;
      if (qtyDiff !== 0) {
        const box = boxes.find(b => b.boxNum === oldEntry.boxNum);
        if (box) {
          const newRemaining = box.remaining - qtyDiff;
          const newConsumed = box.consumed + qtyDiff;
          setBoxes(prev => prev.map(b => 
            b.boxNum === oldEntry.boxNum 
              ? { ...b, remaining: newRemaining, consumed: newConsumed }
              : b
          ));
          if (isSignedIn && accessToken) {
            updateBoxConsumed({ ...box, remaining: newRemaining, consumed: newConsumed });
          }
        }
      }
    }
    
    // Update sheet in place
    await updateHistoryEntry(oldEntry, newEntry, accessToken);
  }}
  onDelete={async (index, entry) => {
    await handleDeleteHistory(index, entry);
    setEditingHistory(null);
  }}
/>}
      
      {/* Bottom buttons */}
      <div className="fixed bottom-4 left-4 right-4 z-30 flex gap-3">
        <button onClick={() => isSignedIn ? setShowAddModal(true) : setShowSignInPrompt(true)} className="flex-1 py-4 rounded-xl font-semibold shadow-lg text-lg" style={{ background: '#1a120b', color: '#F5DEB3', border: '1px solid #F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>
          Add Box
        </button>
        <button onClick={() => isSignedIn ? setShowLogModal(true) : setShowSignInPrompt(true)} className="flex-1 py-4 rounded-xl font-semibold shadow-lg text-lg" style={{ background: '#1a120b', color: '#F5DEB3', border: '1px solid #F5DEB3', fontFamily: 'tt-ricordi-allegria, Georgia, serif' }}>
          Log Smoke
        </button>
      </div>
    </div>
  );
}
