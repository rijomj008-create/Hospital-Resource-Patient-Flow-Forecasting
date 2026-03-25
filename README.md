# Azure Function Project

This project is an Azure Function that utilizes a Timer Trigger to run daily at 08:15 UTC. The function fetches data from a specified URL, processes it, and uploads the results to Azure Blob Storage.

## Project Structure

```
azure-function-project
├── .vscode
│   └── settings.json
├── TimerTriggerFunction
│   ├── __init__.py
│   ├── function.json
│   └── requirements.txt
├── host.json
├── local.settings.json
└── README.md
```

## Components

### TimerTriggerFunction/__init__.py
This file contains the main logic for the Azure Function. It fetches data from the specified URL, parses the first HTML table using pandas, cleans the columns, and uploads the resulting CSV file to Azure Blob Storage using the connection string stored in the `BLOB_CONN_STR` environment variable.

### TimerTriggerFunction/function.json
This file defines the configuration for the Timer Trigger function. It specifies the schedule for the function to run, which is set to `0 15 8 * * *`, meaning it will execute daily at 08:15 UTC.

### TimerTriggerFunction/requirements.txt
This file lists the dependencies required for the project. It includes:
- requests
- pandas
- azure-storage-blob
- lxml

### .vscode/settings.json
This file contains settings specific to the development environment for the project.

### host.json
This file contains global configuration options for all functions in the function app.

### local.settings.json
This file is used for local development settings, including environment variables such as `BLOB_CONN_STR`.

## Setup Instructions

1. Clone the repository or download the project files.
2. Install the required dependencies by running:
   ```
   pip install -r TimerTriggerFunction/requirements.txt
   ```
3. Set up your Azure Blob Storage connection string in the `local.settings.json` file under the `BLOB_CONN_STR` key.
4. Run the function locally using the Azure Functions Core Tools.

## Testing

A unittest file will be created to mock the requests and Blob upload functionality, ensuring that the function can be tested without making actual HTTP requests or uploads. 

## License

This project is licensed under the MIT License.