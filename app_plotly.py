import streamlit as st
import pandas as pd
import plotly.express as px
from db_utils import get_folders, get_email_data, get_response_data

st.set_page_config(layout="wide")
st.title("Email Analytics Dashboard")

# Load data
folders = get_folders()
all_email_df = get_email_data(None)
response_df = get_response_data()

# Convert datetime
all_email_df['received_date'] = pd.to_datetime(all_email_df['received_date'])
all_email_df['date'] = all_email_df['received_date'].dt.date
response_df['response_time_seconds'] = response_df['response_time_seconds'].astype(float)

# Date range defaults
max_date = all_email_df['received_date'].max().date()
min_date = all_email_df['received_date'].min().date()
default_start_date = max_date - pd.Timedelta(days=13)
default_end_date = max_date

# Apply filters based on session state or use default
selected_folders = st.session_state.get('custom_folders', folders)
start_date = st.session_state.get('custom_start', default_start_date)
end_date = st.session_state.get('custom_end', default_end_date)

# Apply filtering
filtered_df = all_email_df[
    (all_email_df['received_date'].dt.date >= start_date) &
    (all_email_df['received_date'].dt.date <= end_date) &
    (all_email_df['folder'].isin(selected_folders))
]

# Merge with response data
merged = pd.merge(filtered_df, response_df, on='thread_id', suffixes=('', '_resp'))
merged['response_delay'] = merged['response_time_seconds'] / 60
merged['date'] = merged['received_date'].dt.date

# ------------------ PLOTS ------------------
st.header(f"Visualizations ({start_date} to {end_date}) - Selected Folders")

# 1. Email Volume by Folder Over Time
volume_comparison = (
    filtered_df.groupby(['date', 'folder'])
    .size()
    .reset_index(name='Email Count')
)
fig_vol = px.bar(volume_comparison, x='date', y='Email Count', color='folder', barmode='relative',
                 title="Email Volume by Folder Over Time")
st.plotly_chart(fig_vol, use_container_width=True)

# 2. Total Email Count by Date
count_by_date = filtered_df.groupby('date').size().reset_index(name='Email Count')
fig_count_date = px.bar(count_by_date, x='date', y='Email Count', title="Total Email Count by Date")
st.plotly_chart(fig_count_date, use_container_width=True)

# 3. Response Rate (All Folders)
if not filtered_df.empty:
    response_rate = len(merged['email_id'].unique()) / len(filtered_df['email_id'].unique()) * 100
    st.metric(label="Overall Response Rate (%)", value=f"{response_rate:.2f}")
else:
    st.warning("No emails in the selected date range.")

# 4. Average Response Time
if not merged.empty:
    avg_resp_time = merged['response_delay'].mean()
    st.metric(label="Avg. Response Time (minutes)", value=f"{avg_resp_time:.1f}")

# 5. Response Rate by Folder
response_rate_by_folder = merged.groupby('folder').size() / filtered_df.groupby('folder').size() * 100
response_rate_by_folder = response_rate_by_folder.reset_index(name="Response Rate (%)")
fig_resp_folder = px.bar(response_rate_by_folder, x='folder', y='Response Rate (%)',
                         title="Avg. Response Rate by Folder")
st.plotly_chart(fig_resp_folder, use_container_width=True)

# 6. Response Rate by Folder by Date
total_emails = filtered_df.groupby(['folder', 'date']).size().rename("Total Emails")
responded_emails = merged.groupby(['folder', 'date']).size().rename("Responded Emails")
resp_rate_folder_date = pd.concat([total_emails, responded_emails], axis=1).fillna(0)
resp_rate_folder_date['Response Rate (%)'] = (
    resp_rate_folder_date['Responded Emails'] / resp_rate_folder_date['Total Emails'] * 100
)
resp_rate_folder_date = resp_rate_folder_date.reset_index()
fig_resp_rate_trend = px.bar(resp_rate_folder_date, x='date', y='Response Rate (%)', color='folder',
                             title="Response Rate by Folder by Date", barmode='relative')
st.plotly_chart(fig_resp_rate_trend, use_container_width=True)

# 7. Avg. Response Time by Folder by Date
avg_resp_time_df = merged.groupby(['folder', 'date'])['response_delay'].mean().reset_index()
avg_resp_time_df.rename(columns={'response_delay': 'Avg. Response Time (min)'}, inplace=True)
fig_avg_resp_time = px.bar(avg_resp_time_df, x='date', y='Avg. Response Time (min)', color='folder',
                           title="Avg. Response Time by Folder by Date", barmode='relative')
st.plotly_chart(fig_avg_resp_time, use_container_width=True)

# 8. Responded Emails per Folder by Date
responded_counts = merged.groupby(['date', 'folder']).size().reset_index(name='Responded Emails')
fig_responded = px.bar(responded_counts, x='date', y='Responded Emails', color='folder',
                       title="Responded Emails per Folder by Date", barmode='relative')
st.plotly_chart(fig_responded, use_container_width=True)

# ------------------ SUMMARY TABLE ------------------
st.header("Folder-Wise Summary Table")

summary_df = filtered_df.groupby('folder').agg(Total_Emails=('email_id', 'count')).reset_index()
responded_df = merged.groupby('folder').agg(
    Responded_Emails=('email_id', 'count'),
    Avg_Response_Time_Min=('response_delay', 'mean')
).reset_index()

folder_summary = pd.merge(summary_df, responded_df, on='folder', how='left')
folder_summary['Response Rate (%)'] = (
    folder_summary['Responded_Emails'] / folder_summary['Total_Emails'] * 100
).fillna(0).round(2)
folder_summary['Avg_Response_Time_Min'] = folder_summary['Avg_Response_Time_Min'].fillna(0).round(1)

st.dataframe(folder_summary.rename(columns={
    'folder': 'Folder',
    'Total_Emails': 'Total Emails',
    'Responded_Emails': 'Responded Emails',
    'Avg_Response_Time_Min': 'Avg. Response Time (min)'
}), use_container_width=True)

# ------------------ FILTER CONTROLS ------------------
st.header("Modify Filters")

selected_folders_input = st.multiselect("Select Folders", folders, default=selected_folders)
start_date_input, end_date_input = st.date_input(
    "Select Date Range",
    value=(start_date, end_date),
    min_value=min_date,
    max_value=max_date
)

if st.button("Update Dashboard with Selected Filters"):
    st.session_state['custom_folders'] = selected_folders_input
    st.session_state['custom_start'] = start_date_input
    st.session_state['custom_end'] = end_date_input
    st.experimental_rerun()
